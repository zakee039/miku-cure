import time
import os
import sys
import threading
from dotenv import load_dotenv

# Add backend directory to path to support running directly
sys.path.append(os.path.dirname(__file__))

from camera import Camera
from detector import EmotionDetector
from logger import EmotionLogger
from llm import MikuLLM
from websocket_server import MikuWebSocketServer

# Global State Variables
is_running = True
focus_active = False
focus_duration_mins = 30
focus_start_time = 0
current_lang = 'zh'   # Active UI/log language

import collections
# Negative emotion trigger tracking
negative_emotions_set = {'sadness', 'anger', 'fear', 'disgust'}
emotion_window = collections.deque()
care_popup_triggered = False

# Instantiate components
camera = Camera(device_index=0, target_fps=1)
detector = EmotionDetector(model_type='cnn')
logger = EmotionLogger()
llm = MikuLLM()
ws_server = MikuWebSocketServer()

def handle_frontend_message(data):
    """
    Callback to handle incoming JSON commands from Electron frontend.
    """
    global focus_active, focus_duration_mins, focus_start_time
    global emotion_window, care_popup_triggered
    global current_lang
    
    msg_type = data.get('type')
    
    if msg_type == 'start_focus':
        focus_duration_mins = data.get('duration_minutes', 30)
        focus_active = True
        focus_start_time = time.time()
        
        # Reset negative emotion tracking
        emotion_window.clear()
        care_popup_triggered = False
        
        logger.lang = current_lang
        logger.start_session(duration_minutes=focus_duration_mins)
        print(f"Backend: Focus started for {focus_duration_mins} minutes (lang={current_lang}).")
        
    elif msg_type == 'end_focus':
        if not focus_active:
            return
            
        completed = data.get('completed', True)
        focus_active = False
        
        # 1. Get temporary stats to feed to LLM
        emotion_durations = {}
        for entry in logger.current_session_entries:
            emotion_durations[entry.emotion] = emotion_durations.get(entry.emotion, 0) + entry.duration
            
        total_seconds = sum(emotion_durations.values()) or 1
        stats = {em: (emotion_durations.get(em, 0) / total_seconds) * 100 for em in detector.EMOTIONS}
        
        def _process_end_focus():
            # 2. Get LLM response
            comment = llm.get_focus_end_response(focus_duration_mins, stats, lang=current_lang)
            
            # 3. Finalize log entry in markdown
            final_stats, actual_minutes = logger.end_session(completed=completed, miku_comment=comment)
            
            # 4. Push report back to Electron frontend
            ws_server.send_to_all({
                "type": "focus_report",
                "duration_minutes": actual_minutes,
                "stats": final_stats,
                "comment": comment,
                "completed": completed
            })
            print("Backend: Focus ended. Report sent to frontend.")
            
        threading.Thread(target=_process_end_focus, daemon=True).start()
        
    elif msg_type == 'care_popup_dismissed':
        # User dismissed the Miku care popup, reset window and allow triggers again
        care_popup_triggered = False
        emotion_window.clear()
        print("Backend: Care popup dismissed by user, window reset.")

    elif msg_type == 'change_model':
        model_type = data.get('model_type', 'cnn')
        detector.switch_model(model_type)

    elif msg_type == 'set_lang':
        # Language change from frontend
        lang = data.get('lang', 'zh')
        if lang in ('zh', 'ja', 'en'):
            current_lang = lang
            logger.lang  = lang
            print(f"Backend: Language set to '{lang}'.")

    elif msg_type == 'change_llm':
        # Hot-swap LLM API configuration from settings
        base_url = data.get('base_url', '')
        api_key  = data.get('api_key',  '')
        model    = data.get('model',    '')
        llm.reconfigure(base_url=base_url, api_key=api_key, model=model)
        print(f"Backend: LLM reconfigured → {base_url} / {model}")
        ws_server.send_to_all({'type': 'llm_status', 'base_url': llm.base_url, 'model': llm.model, 'has_key': bool(llm.api_key)})

    elif msg_type == 'toggle_camera':
        state = data.get('state', True)
        if state:
            camera.start()
            print("Backend: Camera started by user.")
        else:
            camera.stop()
            print("Backend: Camera stopped by user.")

    elif msg_type == 'chat_request':
        text = data.get('text', '')
        hidden_context = data.get('hidden_context', None)
        def _process_chat():
            reply = llm.chat_with_miku(text, hidden_context=hidden_context, lang=current_lang)
            ws_server.send_to_all({
                'type': 'chat_reply',
                'text': reply
            })
            print(f"Backend: Handled chat request")
        threading.Thread(target=_process_chat, daemon=True).start()

    elif msg_type == 'get_chat_history':
        ws_server.send_to_all({
            'type': 'chat_history_response',
            'history': llm.chat_history
        })
        print(f"Backend: Sent chat history to frontend")

    elif msg_type == 'download_deepface':
        def _download():
            import urllib.request
            url = "https://ghproxy.com/https://github.com/serengil/deepface_models/releases/download/v1.0/facial_expression_model_weights.h5"
            target_dir = os.path.expanduser("~/.deepface/weights")
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, "facial_expression_model_weights.h5")
            
            try:
                start_time = time.time()
                def reporthook(count, block_size, total_size):
                    duration = time.time() - start_time
                    progress_size = count * block_size
                    speed = int(progress_size / (1024 * duration)) if duration > 0 else 0
                    progress = min(100, int(progress_size * 100 / total_size)) if total_size > 0 else 0
                    
                    if not hasattr(reporthook, 'last_update') or (time.time() - reporthook.last_update > 0.2) or progress == 100:
                        ws_server.send_to_all({
                            "type": "download_progress",
                            "progress": progress,
                            "speed": f"{speed} KB/s"
                        })
                        reporthook.last_update = time.time()
                        
                urllib.request.urlretrieve(url, target_path, reporthook)
                ws_server.send_to_all({"type": "download_complete", "success": True})
                print("Backend: DeepFace weights downloaded successfully.")
            except Exception as e:
                print(f"Backend: DeepFace download failed: {e}")
                ws_server.send_to_all({"type": "download_complete", "success": False, "error": str(e)})
                
        threading.Thread(target=_download, daemon=True).start()
        print("Backend: Started downloading DeepFace weights...")

    elif msg_type == 'delete_lora_data':
        lora_dir = os.path.join(os.path.dirname(__file__), '..', 'user', 'lora')
        weights_file = os.path.join(lora_dir, 'lora_weights.pth')
        name_file = os.path.join(lora_dir, 'master_name.txt')
        try:
            if os.path.exists(weights_file): os.remove(weights_file)
            if os.path.exists(name_file): os.remove(name_file)
            # Reload model without LoRA
            detector.switch_model(detector.model_type)
            print("Backend: LoRA data deleted and model reloaded.")
        except Exception as e:
            print(f"Backend: Error deleting LoRA data: {e}")

    elif msg_type == 'start_lora_training':
        master_name = data.get('master_name', '用户')
        images_data = data.get('data', [])
        
        # Save master name
        lora_dir = os.path.join(os.path.dirname(__file__), '..', 'user', 'lora')
        os.makedirs(lora_dir, exist_ok=True)
        with open(os.path.join(lora_dir, 'master_name.txt'), 'w', encoding='utf-8') as f:
            f.write(master_name)
            
        def _train_lora():
            import base64
            import numpy as np
            import cv2
            import torch
            import torch.nn as nn
            import torch.optim as optim
            from lora import inject_lora
            
            try:
                print(f"Backend: Starting LoRA training for master {master_name} with {len(images_data)} images...")
                
                # Decode images and preprocess
                tensors = []
                targets = []
                
                for item in images_data:
                    label = item['label']
                    b64_img = item['image'].split(',')[1] if ',' in item['image'] else item['image']
                    img_bytes = base64.b64decode(b64_img)
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    
                    face_img, _ = detector.extract_face(frame)
                    if face_img is not None and face_img.size > 0:
                        t = detector.preprocess_to_tensor(face_img)
                        tensors.append(t)
                        
                        class_idx = detector.EMOTIONS.index(label)
                        targets.append(class_idx)
                
                if not tensors:
                    raise ValueError("No valid faces found in the training images.")
                    
                X = torch.cat(tensors, dim=0)
                Y = torch.tensor(targets, dtype=torch.long).to(detector.device)
                
                # Inject LoRA into current model
                detector.model = inject_lora(detector.model).to(detector.device)
                
                # Freeze all parameters except LoRA
                for name, param in detector.model.named_parameters():
                    if 'lora_' not in name:
                        param.requires_grad = False
                    else:
                        param.requires_grad = True
                        
                detector.model.train()
                optimizer = optim.Adam(filter(lambda p: p.requires_grad, detector.model.parameters()), lr=0.005)
                criterion = nn.CrossEntropyLoss()
                
                epochs = 30
                for epoch in range(epochs):
                    optimizer.zero_grad()
                    outputs = detector.model(X)
                    loss = criterion(outputs, Y)
                    loss.backward()
                    optimizer.step()
                    print(f"LoRA Epoch {epoch+1}/{epochs}, Loss: {loss.item():.4f}")
                    progress = int(((epoch + 1) / epochs) * 100)
                    ws_server.send_to_all({"type": "training_progress", "progress": progress})
                
                detector.model.eval()
                
                # Save only LoRA weights
                lora_state = {k: v for k, v in detector.model.state_dict().items() if 'lora_' in k}
                torch.save(lora_state, os.path.join(lora_dir, 'lora_weights.pth'))
                print("Backend: LoRA weights saved successfully.")
                
                ws_server.send_to_all({"type": "training_complete", "success": True})
            except Exception as e:
                print(f"Backend: LoRA training failed: {e}")
                ws_server.send_to_all({"type": "training_complete", "success": False, "error": str(e)})
            finally:
                camera.start()
                
        threading.Thread(target=_train_lora, daemon=True).start()

def main_loop():
    global is_running, focus_active
    global emotion_window, care_popup_triggered
    
    print("Backend: Main detection loop running.")
    while is_running:
        start_time = time.time()
        
        # 1. Grab camera frame
        frame = camera.get_frame()
        if frame is not None:
            # 2. Detect emotion
            emotion, confidence, bbox = detector.detect_emotion(frame)
            
            # Pack bbox to json-friendly list [x, y, w, h]
            bbox_list = list(bbox) if bbox else None
            
            # 3. Broadcast real-time update
            ws_server.send_to_all({
                "type": "emotion_update",
                "emotion": emotion,
                "confidence": confidence,
                "bbox": bbox_list
            })
            
            # 4. Handle global proactive care window tracking
            if not care_popup_triggered:
                # Add to sliding window (timestamp, emotion)
                emotion_window.append((time.time(), emotion))
                # Prune old entries (>30s)
                while emotion_window and time.time() - emotion_window[0][0] > 30.0:
                    emotion_window.popleft()
                
                # Check negative emotion count
                neg_count = sum(1 for _, em in emotion_window if em in negative_emotions_set)
                if neg_count > 20:
                    print(f"Backend: Triggered proactive care popup (negatives={neg_count}/30s)")
                    care_popup_triggered = True
                    
                    def _trigger_care():
                        # Find the most frequent negative emotion to give context to LLM
                        neg_emotions = [em for _, em in emotion_window if em in negative_emotions_set]
                        most_frequent = max(set(neg_emotions), key=neg_emotions.count) if neg_emotions else 'sadness'
                        
                        comment = llm.get_unhappy_response(most_frequent, duration_seconds=30, lang=current_lang)
                        ws_server.send_to_all({
                            "type": "trigger_care_popup",
                            "text": comment
                        })
                    threading.Thread(target=_trigger_care, daemon=True).start()

            # Handle focus session logging
            if focus_active:
                logger.log_emotion(emotion, confidence)
        
        # Sleep for remainder of the second to maintain ~1Hz tick rate
        elapsed = time.time() - start_time
        sleep_dur = 1.0 - elapsed
        if sleep_dur > 0:
            time.sleep(sleep_dur)

if __name__ == '__main__':
    print("Miku Emotion Companion Backend Starting...")
    
    # Start WebSocket Server
    ws_server.start(handle_frontend_message)
    
    # Start Camera Acquisition
    if not camera.start():
        print("Fatal: Could not initialize camera. Exiting...")
        ws_server.stop()
        sys.exit(1)
        
    try:
        # Start main loop
        main_loop()
    except KeyboardInterrupt:
        print("Backend: Exiting on user interrupt...")
    finally:
        is_running = False
        camera.stop()
        ws_server.stop()
        print("Miku Emotion Companion Backend Cleaned Up.")
