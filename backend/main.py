import time
import os
import sys
import collections
from concurrent.futures import ThreadPoolExecutor, Future
from dotenv import load_dotenv

sys.path.append(os.path.dirname(__file__))

from camera import Camera
from detector import EmotionDetector
from logger import EmotionLogger
from llm import MikuLLM
from websocket_server import MikuWebSocketServer

load_dotenv()

# Global State
is_running = True
focus_active = False
focus_paused = False
focus_duration_mins = 30
focus_start_time = 0
focus_paused_seconds = 0.0
_pause_started_at = None
current_lang = 'zh'
camera_monitor_on_start = os.environ.get('MIKU_CAMERA_MONITOR_ON_START', '1') != '0'

negative_emotions_set = {'sadness', 'anger', 'fear', 'disgust'}
emotion_window = collections.deque()
care_popup_triggered = False
care_cooldown_until = 0.0
CARE_COOLDOWN_SEC = 600.0
MIN_SESSION_SAVE_SEC = 30  # skip writing reports for tiny accidental sessions

# Real-time display: ~2 FPS capture, no temporal smoothing
camera = Camera(device_index=0, target_fps=2)
# Default: RNN + Attention weights (no DeepFace)
detector = EmotionDetector(model_type='best_rnn_attention.pth')
logger = EmotionLogger(flush_interval_sec=15.0)
llm = MikuLLM()
ws_server = MikuWebSocketServer()

# Workers: general IO/LLM + single-slot inference (latest-frame only)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='miku-worker')
infer_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='miku-infer')
_infer_future = None  # type: Future | None
_infer_seq = 0

# Let LLM reuse the shared pool for memory summarization
llm.set_executor(executor)


def _camera_status_payload(error=None):
    payload = {
        'type': 'camera_status',
        'connected': bool(camera.is_running),
    }
    if error:
        payload['error'] = error
    return payload


def _accumulate_pause():
    global focus_paused_seconds, _pause_started_at
    if _pause_started_at is not None:
        focus_paused_seconds += max(0.0, time.time() - _pause_started_at)
        _pause_started_at = None


def handle_frontend_message(data):
    global focus_active, focus_duration_mins, focus_start_time, focus_paused
    global focus_paused_seconds, _pause_started_at
    global emotion_window, care_popup_triggered, care_cooldown_until
    global current_lang

    msg_type = data.get('type')

    if msg_type == 'ping':
        ws_server.send_to_all({'type': 'pong', 'ts': time.time()})
        return

    if msg_type == 'start_focus':
        focus_duration_mins = data.get('duration_minutes', 30)
        focus_active = True
        focus_paused = False
        focus_start_time = time.time()
        focus_paused_seconds = 0.0
        _pause_started_at = None

        emotion_window.clear()
        care_popup_triggered = False

        logger.lang = current_lang
        logger.start_session(duration_minutes=focus_duration_mins)
        print(f"Backend: Focus started for {focus_duration_mins} minutes (lang={current_lang}).")

    elif msg_type == 'pause_focus':
        if not focus_active:
            return
        want_pause = bool(data.get('paused', True))
        if want_pause and not focus_paused:
            focus_paused = True
            _pause_started_at = time.time()
            print("Backend: Focus paused.")
        elif not want_pause and focus_paused:
            _accumulate_pause()
            focus_paused = False
            print(f"Backend: Focus resumed (paused_total={focus_paused_seconds:.0f}s).")

    elif msg_type == 'end_focus':
        if not focus_active:
            return

        completed = data.get('completed', True)
        if focus_paused:
            _accumulate_pause()
        focus_active = False
        focus_paused = False

        planned_mins = focus_duration_mins
        lang_snap = current_lang
        paused_snap = focus_paused_seconds
        emotion_durations = {}
        for entry in logger.current_session_entries:
            emotion_durations[entry.emotion] = emotion_durations.get(entry.emotion, 0) + entry.duration

        total_seconds = sum(emotion_durations.values()) or 1
        stats = {em: (emotion_durations.get(em, 0) / total_seconds) * 100 for em in detector.EMOTIONS}

        def _process_end_focus():
            comment = llm.get_focus_end_response(planned_mins, stats, lang=lang_snap)
            final_stats, actual_minutes = logger.end_session(
                completed=completed,
                miku_comment=comment,
                paused_seconds=int(paused_snap),
                min_save_seconds=MIN_SESSION_SAVE_SEC,
            )
            ws_server.send_to_all({
                "type": "focus_report",
                "duration_minutes": actual_minutes,
                "stats": final_stats,
                "comment": comment,
                "completed": completed,
                "paused_seconds": int(paused_snap),
            })
            print("Backend: Focus ended. Report sent to frontend.")

        executor.submit(_process_end_focus)

    elif msg_type == 'care_popup_dismissed':
        care_popup_triggered = False
        emotion_window.clear()
        care_cooldown_until = time.time() + CARE_COOLDOWN_SEC
        print("Backend: Care popup dismissed by user, cooldown started.")

    elif msg_type == 'change_model':
        model_type = data.get('model_type', 'best_rnn_attention.pth')
        # Reject legacy engine names (DeepFace fully removed)
        mt = str(model_type).lower().strip()
        if mt in ('deepface', 'df') or 'deepface' in mt:
            print("Backend: ignoring obsolete model_type (DeepFace removed); keep RNN default")
            return
        # Model swap on infer thread to avoid racing with in-flight detect
        def _swap():
            detector.switch_model(model_type)
        infer_executor.submit(_swap)

    elif msg_type == 'set_lang':
        lang = data.get('lang', 'zh')
        if lang in ('zh', 'ja', 'en'):
            current_lang = lang
            logger.lang = lang
            print(f"Backend: Language set to '{lang}'.")

    elif msg_type == 'change_llm':
        base_url = data.get('base_url', '')
        api_key = data.get('api_key', '')
        model = data.get('model', '')
        llm.reconfigure(base_url=base_url, api_key=api_key, model=model)
        print(f"Backend: LLM reconfigured → {base_url} / {model}")
        ws_server.send_to_all({
            'type': 'llm_status',
            'base_url': llm.base_url,
            'model': llm.model,
            'has_key': bool(llm.api_key),
        })

    elif msg_type == 'toggle_camera':
        requested_state = bool(data.get('state', True))
        error = None
        if requested_state:
            if camera.start():
                print("Backend: Camera started by user.")
            else:
                error = 'camera_open_failed'
                print("Backend: Camera could not be started by user.")
        else:
            camera.stop()
            print("Backend: Camera stopped by user.")
        ws_server.send_to_all(_camera_status_payload(error))

    elif msg_type == 'chat_request':
        text = data.get('text', '')
        hidden_context = data.get('hidden_context', None)
        lang_snap = current_lang

        def _process_chat():
            reply = llm.chat_with_miku(text, hidden_context=hidden_context, lang=lang_snap)
            ws_server.send_to_all({'type': 'chat_reply', 'text': reply})
            print("Backend: Handled chat request")

        executor.submit(_process_chat)

    elif msg_type == 'get_chat_history':
        llm.check_new_day()
        ws_server.send_to_all({
            'type': 'chat_history_response',
            'history': llm.chat_history
        })
        print("Backend: Sent chat history to frontend")

    elif msg_type == 'delete_lora_data':
        user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(os.path.dirname(__file__), '..', 'user')
        lora_dir = os.path.join(user_root, 'lora')
        weights_file = os.path.join(lora_dir, 'lora_weights.pth')
        name_file = os.path.join(lora_dir, 'master_name.txt')
        try:
            if os.path.exists(weights_file):
                os.remove(weights_file)
            if os.path.exists(name_file):
                os.remove(name_file)

            def _reload():
                detector.switch_model(detector.model_type, force=True)

            infer_executor.submit(_reload)
            print("Backend: LoRA data deleted and model reload queued.")
        except Exception as e:
            print(f"Backend: Error deleting LoRA data: {e}")

    elif msg_type == 'start_lora_training':
        master_name = data.get('master_name', '用户')
        images_data = data.get('data', [])

        user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(os.path.dirname(__file__), '..', 'user')
        lora_dir = os.path.join(user_root, 'lora')
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

                if detector.model is None:
                    raise ValueError("No base model loaded — cannot train LoRA. Select a PyTorch model first.")

                detector.model = inject_lora(detector.model).to(detector.device)

                for name, param in detector.model.named_parameters():
                    param.requires_grad = 'lora_' in name

                detector.model.train()
                optimizer = optim.Adam(
                    filter(lambda p: p.requires_grad, detector.model.parameters()), lr=0.005
                )
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

                lora_state = {k: v for k, v in detector.model.state_dict().items() if 'lora_' in k}
                torch.save(lora_state, os.path.join(lora_dir, 'lora_weights.pth'))
                print("Backend: LoRA weights saved successfully.")

                ws_server.send_to_all({"type": "training_complete", "success": True})
            except Exception as e:
                print(f"Backend: LoRA training failed: {e}")
                ws_server.send_to_all({"type": "training_complete", "success": False, "error": str(e)})
            finally:
                try:
                    camera.start()
                except Exception:
                    pass

        # Run on infer executor so it doesn't race with detect_emotion
        infer_executor.submit(_train_lora)


def _handle_emotion_result(emotion, confidence, bbox):
    """Post-process a finished inference result on the main loop thread."""
    global care_popup_triggered, care_cooldown_until

    # Frontend currently does not draw bbox — omit to shrink WS payload
    ws_server.send_to_all({
        "type": "emotion_update",
        "emotion": emotion,
        "confidence": float(confidence),
    })

    now = time.time()
    if (
        emotion != 'no_face'
        and not care_popup_triggered
        and now >= care_cooldown_until
    ):
        emotion_window.append((now, emotion))
        while emotion_window and now - emotion_window[0][0] > 30.0:
            emotion_window.popleft()

        neg_count = sum(1 for _, em in emotion_window if em in negative_emotions_set)
        window_len = max(1, len(emotion_window))
        if neg_count > 20 and (neg_count / window_len) >= 0.6:
            print(f"Backend: Triggered proactive care popup (negatives={neg_count}/{window_len})")
            care_popup_triggered = True
            care_cooldown_until = now + CARE_COOLDOWN_SEC
            lang_snap = current_lang
            neg_emotions = [em for _, em in emotion_window if em in negative_emotions_set]
            most_frequent = max(set(neg_emotions), key=neg_emotions.count) if neg_emotions else 'sadness'

            def _trigger_care():
                comment = llm.get_unhappy_response(most_frequent, duration_seconds=30, lang=lang_snap)
                ws_server.send_to_all({
                    "type": "trigger_care_popup",
                    "text": comment
                })

            executor.submit(_trigger_care)

    if focus_active and not focus_paused and emotion != 'no_face':
        logger.log_emotion(emotion, confidence)


def main_loop():
    """
    Main tick ~2Hz (0.5s).
    Inference runs async; results are applied as soon as ready (not delayed one full tick).
    Intermediate frames dropped if still busy (backpressure-safe).
    """
    global is_running, _infer_future, _infer_seq

    tick = 0.5  # seconds — matches target_fps≈2
    print("Backend: Main detection loop running (async inference, ~2Hz).")
    while is_running:
        start_time = time.time()

        # Collect finished inference immediately
        if _infer_future is not None and _infer_future.done():
            try:
                emotion, confidence, bbox = _infer_future.result()
                _handle_emotion_result(emotion, confidence, bbox)
            except Exception as e:
                print(f"Backend: Inference error: {e}")
            _infer_future = None

        # Submit new work only when idle — drop intermediate frames
        if _infer_future is None:
            frame = camera.get_frame()
            if frame is not None:
                _infer_seq += 1

                def _run_detect(f=frame):
                    return detector.detect_emotion(f)

                _infer_future = infer_executor.submit(_run_detect)

        elapsed = time.time() - start_time
        sleep_dur = tick - elapsed
        if sleep_dur > 0:
            time.sleep(sleep_dur)


def _pid_file_path():
    user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(
        os.path.dirname(__file__), '..', 'user'
    )
    return os.path.join(user_root, 'backend.pid')


def _write_pid_file():
    path = _pid_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
        print(f"Backend: PID file → {path} ({os.getpid()})")
    except Exception as e:
        print(f"Backend: Failed to write PID file: {e}")


def _clear_pid_file():
    path = _pid_file_path()
    try:
        if os.path.exists(path):
            # Only remove if it still points to us
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    if f.read().strip() != str(os.getpid()):
                        return
            except Exception:
                pass
            os.remove(path)
    except Exception:
        pass


def _parent_alive():
    """Return False if our parent process is gone (Electron exited without killing us)."""
    try:
        ppid = os.getppid()
        if ppid is None or ppid <= 0:
            return True
        if os.name == 'nt':
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(ppid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        # Unix: signal 0 probes existence
        os.kill(ppid, 0)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    print("Miku Emotion Companion Backend Starting...")
    _write_pid_file()

    def on_client_connect():
        ws_server.send_to_all({
            "type": "backend_ready",
            "version": "1.1.2",
            "model": detector.model_type,
            "camera_enabled": bool(camera.is_running),
            "face_engine": (
                "mp_tasks" if getattr(detector, "mp_tasks_face", None)
                else ("mp_legacy" if detector.mp_face else "haar")
            ),
        })

    ws_server.start(handle_frontend_message, on_connect=on_client_connect)

    # Wait briefly for bind result so logs are truthful
    for _ in range(20):
        if getattr(ws_server, 'bind_ok', False) or getattr(ws_server, 'bind_error', None):
            break
        time.sleep(0.05)
    if not getattr(ws_server, 'bind_ok', False):
        print(
            "FATAL: WebSocket failed to listen. Frontend will show 'disconnected' "
            f"even if the camera works. Error: {getattr(ws_server, 'bind_error', 'unknown')}"
        )
        print("Hint: set MIKU_WS_PORT to a free port, or check Windows excluded ranges:")
        print("      netsh interface ipv4 show excludedportrange protocol=tcp")

    if camera_monitor_on_start:
        cam_ok = camera.start()
        if not cam_ok:
            print("Warning: Camera failed to open — backend continues (toggle_camera / mock still usable).")
    else:
        print("Backend: Camera emotion monitoring disabled at startup.")

    time.sleep(0.3)
    if getattr(ws_server, 'bind_ok', False):
        ws_server.send_to_all({
            "type": "backend_ready",
            "version": "1.1.2",
            "model": detector.model_type,
            "camera_enabled": bool(camera.is_running),
        })
        print("Backend: Ready signal broadcast.")
    else:
        print("Backend: Skipping ready broadcast (WebSocket not listening).")

    # Watchdog: exit if parent process dies.
    # Launcher mode: parent = MikuCure-Launcher (not Electron). Electron is a sibling.
    # Electron-spawned mode: parent = Electron. Either way we stay under the true parent PID tree.
    def _parent_watch():
        global is_running
        while is_running:
            time.sleep(1.5)
            if not _parent_alive():
                print("Backend: Parent process gone — shutting down.")
                is_running = False
                break

    import threading
    threading.Thread(target=_parent_watch, daemon=True).start()

    try:
        main_loop()
    except KeyboardInterrupt:
        print("Backend: Exiting on user interrupt...")
    finally:
        is_running = False
        camera.stop()
        ws_server.stop()
        infer_executor.shutdown(wait=False)
        executor.shutdown(wait=False)
        _clear_pid_file()
        print("Miku Emotion Companion Backend Cleaned Up.")
