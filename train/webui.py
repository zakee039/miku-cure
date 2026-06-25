import os
import sys
import json
import asyncio
import subprocess
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
            
            if cmd.get("action") == "start":
                if training_process is not None and training_process.poll() is None:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Training already running"}))
                    continue
                
                script_path = os.path.join(os.path.dirname(__file__), "train_models.py")
                training_process = subprocess.Popen(
                    [sys.executable, "-u", script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                await websocket.send_text(json.dumps({"type": "status", "status": "running"}))
                
                loop = asyncio.get_event_loop()
                while True:
                    line = await loop.run_in_executor(None, training_process.stdout.readline)
                    if not line and training_process.poll() is not None:
                        break
                    if line:
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
