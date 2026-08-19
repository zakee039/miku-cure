import os
import sys
import json
import asyncio
import subprocess
import datetime
import collections
import math
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import uvicorn

TRAIN_DIR = Path(__file__).resolve().parent
DATASETS_DIR = TRAIN_DIR / "datasets"
MODELS_DIR = TRAIN_DIR / "models"
LOGS_DIR = TRAIN_DIR / "logs"
TRAINING_SCRIPTS = {
    "cnn": TRAIN_DIR / "train_cnn.py",
    "rnn": TRAIN_DIR / "train_rnn.py",
    "mobilenet": TRAIN_DIR / "train_mobilenet.py",
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_COMMAND_BYTES = 16_384

training_process = None
current_training_model = None
recent_logs = collections.deque(maxlen=20)
active_connections = set()


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await _shutdown_training()


app = FastAPI(lifespan=_app_lifespan)


def _is_allowed_origin(origin: str | None) -> bool:
    """Reject cross-site WebSocket control of the local training service."""
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOOPBACK_HOSTS


def _bounded_number(value, *, minimum: float, maximum: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _bounded_integer(value, *, minimum: int, maximum: int, name: str) -> int:
    number = _bounded_number(value, minimum=minimum, maximum=maximum, name=name)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(number)


def _resolve_dataset(name: object) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("Invalid dataset name")
    if Path(name).suffix.lower() != ".csv":
        raise ValueError("Dataset must be a CSV file")
    root = DATASETS_DIR.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError("Dataset does not exist")
    return candidate


def _validated_start_command(cmd: dict) -> tuple[list[str], str, str]:
    model_type = cmd.get("model", "cnn")
    if model_type not in TRAINING_SCRIPTS:
        raise ValueError("Unsupported model type")
    dataset_path = _resolve_dataset(cmd.get("dataset", "fer2013_plus.csv"))
    learning_rate = _bounded_number(
        cmd.get("lr", 0.0001), minimum=1e-8, maximum=1.0, name="Learning rate"
    )
    epochs = _bounded_integer(
        cmd.get("epochs", 30), minimum=1, maximum=5000, name="Epochs"
    )
    batch_size = _bounded_integer(
        cmd.get("batchSize", 64), minimum=1, maximum=4096, name="Batch size"
    )
    dynamic_lr = cmd.get("dynamicLr", False)
    if not isinstance(dynamic_lr, bool):
        raise ValueError("dynamicLr must be a boolean")

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S-%f")
    save_dir = MODELS_DIR / timestamp
    save_dir.mkdir(parents=True, exist_ok=False)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-u",
        str(TRAINING_SCRIPTS[model_type]),
        "--dataset",
        str(dataset_path),
        "--lr",
        format(learning_rate, ".12g"),
        "--epochs",
        str(epochs),
        "--batch_size",
        str(batch_size),
        "--save_dir",
        str(save_dir),
    ]
    if dynamic_lr:
        command.append("--dynamic_lr")
    return command, model_type, timestamp


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Stop the tracked trainer and its data-loader children without PID scanning."""
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        processes = parent.children(recursive=True)
        processes.append(parent)
        for item in reversed(processes):
            item.terminate()
        _, alive = psutil.wait_procs(processes, timeout=3)
        for item in alive:
            item.kill()
    except (psutil.Error, OSError):
        try:
            process.terminate()
        except OSError:
            pass


async def _shutdown_training() -> None:
    """Stop the trainer owned by this WebUI before uvicorn exits."""
    global training_process, current_training_model
    process = training_process
    training_process = None
    current_training_model = None
    if process is not None and process.poll() is None:
        await asyncio.get_running_loop().run_in_executor(
            None, _terminate_process_tree, process
        )
    active_connections.clear()

async def broadcast_msg(msg: dict):
    msg_str = json.dumps(msg)
    stale = []
    for ws in list(active_connections):
        try:
            await ws.send_text(msg_str)
        except Exception:
            stale.append(ws)
    for ws in stale:
        active_connections.discard(ws)

async def log_reader_task(process, log_file_path):
    global training_process, current_training_model
    loop = asyncio.get_event_loop()
    try:
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            while True:
                line = await loop.run_in_executor(None, process.stdout.readline)
                if not line and process.poll() is not None:
                    break
                if line:
                    line_str = line.strip()
                    log_file.write(line)
                    log_file.flush()
                    recent_logs.append(line_str)
                    await broadcast_msg({"type": "log", "line": line_str})
    except Exception as e:
        print(f"Log reader error: {e}")
    finally:
        if training_process is process:
            training_process = None
            current_training_model = None
            await broadcast_msg({"type": "status", "status": "stopped"})

@app.websocket("/ws/train")
async def websocket_train(websocket: WebSocket):
    global training_process, current_training_model
    if not _is_allowed_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if len(data.encode("utf-8")) > MAX_COMMAND_BYTES:
                await websocket.send_json({"type": "error", "message": "Command is too large"})
                continue
            try:
                cmd = json.loads(data)
            except (TypeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON command"})
                continue
            if not isinstance(cmd, dict):
                await websocket.send_json({"type": "error", "message": "Command must be an object"})
                continue
            
            if cmd.get("action") == "get_datasets":
                datasets = sorted(
                    item.name
                    for item in DATASETS_DIR.iterdir()
                    if item.is_file() and item.suffix.lower() == ".csv"
                ) if DATASETS_DIR.exists() else []
                await websocket.send_text(json.dumps({"type": "datasets", "datasets": datasets}))
                continue
                
            elif cmd.get("action") == "get_status":
                status = (
                    "running"
                    if training_process is not None and training_process.poll() is None
                    else "stopped"
                )
                await websocket.send_text(json.dumps({
                    "type": "status", 
                    "status": status,
                    "model": current_training_model
                }))
                if status == "running":
                    await websocket.send_text(json.dumps({
                        "type": "recent_logs",
                        "logs": list(recent_logs)
                    }))
                continue

            elif cmd.get("action") == "start":
                if training_process is not None and training_process.poll() is None:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Training already running"}))
                    continue
                try:
                    command, model_type, timestamp = _validated_start_command(cmd)
                except (OSError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue

                log_file_path = LOGS_DIR / f"{timestamp}-{model_type.upper()}.txt"
                
                current_training_model = model_type
                recent_logs.clear()
                
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                try:
                    training_process = subprocess.Popen(
                        command,
                        cwd=str(TRAIN_DIR),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        creationflags=creation_flags,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    await websocket.send_json({"type": "error", "message": f"Could not start training: {exc}"})
                    continue
                
                await broadcast_msg({"type": "status", "status": "running", "model": model_type})
                asyncio.create_task(log_reader_task(training_process, log_file_path))
                
            elif cmd.get("action") == "stop":
                if training_process is not None:
                    process = training_process
                    await asyncio.get_running_loop().run_in_executor(
                        None, _terminate_process_tree, process
                    )
            
            elif cmd.get("action") == "pause":
                if training_process is not None and training_process.poll() is None:
                    try:
                        p = psutil.Process(training_process.pid)
                        for child in p.children(recursive=True):
                            child.suspend()
                        p.suspend()
                        await broadcast_msg({"type": "status", "status": "paused", "model": current_training_model})
                    except Exception as e:
                        print(f"Pause error: {e}")
                        
            elif cmd.get("action") == "resume":
                if training_process is not None and training_process.poll() is None:
                    try:
                        p = psutil.Process(training_process.pid)
                        p.resume()
                        for child in p.children(recursive=True):
                            child.resume()
                        await broadcast_msg({"type": "status", "status": "running", "model": current_training_model})
                    except Exception as e:
                        print(f"Resume error: {e}")
                
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)

dist_dir = TRAIN_DIR / "frontend" / "dist"
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")

if __name__ == "__main__":
    # Bind localhost by default — training WebUI should not be LAN-exposed
    uvicorn.run("webui:app", host="127.0.0.1", port=8000, reload=False)
