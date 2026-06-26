import os
import sys
import json
import asyncio
import subprocess
import datetime
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

@app.websocket("/ws/train")
async def websocket_train(websocket: WebSocket):
    global training_process
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            cmd = json.loads(data)
            
            if cmd.get("action") == "get_datasets":
                datasets_dir = os.path.join(os.path.dirname(__file__), "datasets")
                datasets = [f for f in os.listdir(datasets_dir) if f.endswith('.csv')] if os.path.exists(datasets_dir) else []
                await websocket.send_text(json.dumps({"type": "datasets", "datasets": datasets}))
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
                elif model_type == "ALL":
                    script_name = "train_all.py"
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
                
                training_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                await websocket.send_text(json.dumps({"type": "status", "status": "running"}))
                
                loop = asyncio.get_event_loop()
                with open(log_file_path, "a", encoding="utf-8") as log_file:
                    while True:
                        line = await loop.run_in_executor(None, training_process.stdout.readline)
                        if not line and training_process.poll() is not None:
                            break
                        if line:
                            log_file.write(line)
                            log_file.flush()
                            await websocket.send_text(json.dumps({"type": "log", "line": line.strip()}))
                
                await websocket.send_text(json.dumps({"type": "status", "status": "stopped"}))
                training_process = None
                
            elif cmd.get("action") == "stop":
                if training_process is not None:
                    training_process.terminate()
                    training_process = None
                await websocket.send_text(json.dumps({"type": "status", "status": "stopped"}))
                
    except WebSocketDisconnect:
        print("WebSocket disconnected")

dist_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(dist_dir):
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("webui:app", host="0.0.0.0", port=8000, reload=True)
