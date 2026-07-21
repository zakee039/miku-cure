import os
import sys
import json
import asyncio
import subprocess
import datetime
import collections
import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

training_process = None
current_training_model = None
recent_logs = collections.deque(maxlen=20)
active_connections = set()

async def broadcast_msg(msg: dict):
    msg_str = json.dumps(msg)
    for ws in list(active_connections):
        try:
            await ws.send_text(msg_str)
        except:
            pass

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
        await broadcast_msg({"type": "status", "status": "stopped"})
        training_process = None
        current_training_model = None

@app.websocket("/ws/train")
async def websocket_train(websocket: WebSocket):
    global training_process, current_training_model
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            cmd = json.loads(data)
            
            if cmd.get("action") == "get_datasets":
                datasets_dir = os.path.join(os.path.dirname(__file__), "datasets")
                datasets = [f for f in os.listdir(datasets_dir) if f.endswith('.csv')] if os.path.exists(datasets_dir) else []
                await websocket.send_text(json.dumps({"type": "datasets", "datasets": datasets}))
                continue
                
            elif cmd.get("action") == "get_status":
                status = "running" if training_process is not None else "stopped"
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
                
                model_type = cmd.get("model", "cnn")
                if model_type == "rnn":
                    script_name = "train_rnn.py"
                elif model_type == "mobilenet":
                    script_name = "train_mobilenet.py"
                else:
                    script_name = "train_cnn.py"
                
                script_path = os.path.join(os.path.dirname(__file__), script_name)
                
                dataset_name = cmd.get("dataset", "fer2013_plus.csv")
                dataset_path = os.path.join(os.path.dirname(__file__), "datasets", dataset_name)
                
                lr = str(cmd.get("lr", 0.0001))
                dynamic_lr = cmd.get("dynamicLr", False)
                epochs = str(cmd.get("epochs", 30))
                batch_size = str(cmd.get("batchSize", 64))
                
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
                save_dir = os.path.join(os.path.dirname(__file__), "models", timestamp)
                log_dir = os.path.join(os.path.dirname(__file__), "logs")
                os.makedirs(save_dir, exist_ok=True)
                os.makedirs(log_dir, exist_ok=True)
                log_file_path = os.path.join(log_dir, f"{timestamp}-{model_type.upper()}.txt")
                
                command = [
                    sys.executable, "-u", script_path,
                    "--dataset", dataset_path,
                    "--lr", lr,
                    "--epochs", epochs,
                    "--batch_size", batch_size,
                    "--save_dir", save_dir
                ]
                
                if dynamic_lr:
                    command.append("--dynamic_lr")
                
                current_training_model = model_type
                recent_logs.clear()
                
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                training_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=creation_flags
                )
                
                await broadcast_msg({"type": "status", "status": "running", "model": model_type})
                asyncio.create_task(log_reader_task(training_process, log_file_path))
                
            elif cmd.get("action") == "stop":
                if training_process is not None:
                    training_process.terminate()
            
            elif cmd.get("action") == "pause":
                if training_process is not None:
                    try:
                        p = psutil.Process(training_process.pid)
                        for child in p.children(recursive=True):
                            child.suspend()
                        p.suspend()
                        await broadcast_msg({"type": "status", "status": "paused", "model": current_training_model})
                    except Exception as e:
                        print(f"Pause error: {e}")
                        
            elif cmd.get("action") == "resume":
                if training_process is not None:
                    try:
                        p = psutil.Process(training_process.pid)
                        p.resume()
                        for child in p.children(recursive=True):
                            child.resume()
                        await broadcast_msg({"type": "status", "status": "running", "model": current_training_model})
                    except Exception as e:
                        print(f"Resume error: {e}")
                
    except WebSocketDisconnect:
        active_connections.remove(websocket)

dist_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")

if __name__ == "__main__":
    # Bind localhost by default — training WebUI should not be LAN-exposed
    uvicorn.run("webui:app", host="127.0.0.1", port=8000, reload=True)
