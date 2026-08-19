import time
import os
import sys
import collections
import base64
import binascii
import json
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dotenv import load_dotenv

sys.path.append(os.path.dirname(__file__))

from camera import Camera
from detector import EmotionDetector
from logger import EmotionLogger
from llm import MikuLLM
from websocket_server import MikuWebSocketServer
from ws_config import verify_launcher_heartbeat, verify_shutdown_command


class _BrokenPipeSafeTextIO:
    """Keep lifecycle threads alive after their launcher log pipe disappears."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, value):
        try:
            return self._stream.write(value)
        except (BrokenPipeError, OSError, ValueError):
            return len(value)

    def flush(self):
        try:
            return self._stream.flush()
        except (BrokenPipeError, OSError, ValueError):
            return None

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _protect_process_output():
    if not isinstance(sys.stdout, _BrokenPipeSafeTextIO):
        sys.stdout = _BrokenPipeSafeTextIO(sys.stdout)
    if not isinstance(sys.stderr, _BrokenPipeSafeTextIO):
        sys.stderr = _BrokenPipeSafeTextIO(sys.stderr)


load_dotenv()

if __name__ == '__main__' and not os.environ.get('MIKU_WS_TOKEN'):
    print(
        'FATAL: MIKU_WS_TOKEN is required. Start the backend through the launcher/Electron, '
        'or set a random token of at least 16 characters for standalone development.'
    )
    raise SystemExit(2)

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
launcher_heartbeat_expected = os.environ.get('MIKU_EXPECT_LAUNCHER_HEARTBEAT') == '1'
LAUNCHER_HEARTBEAT_TIMEOUT_SEC = 6.0
LAUNCHER_HEARTBEAT_POLL_SEC = 0.5

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
camera.set_status_callback(
    lambda connected, error=None: ws_server.send_to_all(
        _camera_status_payload(error=error, connected=connected)
    )
)

# Workers: general IO/LLM + single-slot inference (latest-frame only)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='miku-worker')
infer_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='miku-infer')
_infer_future = None  # type: Future | None
_infer_seq = 0
_shutdown_event = threading.Event()
_lora_training_lock = threading.Lock()
_worker_futures = set()
_worker_futures_lock = threading.Lock()
_fast_exit_requested = False

# Let LLM reuse the shared pool for memory summarization
llm.set_executor(executor)


def _camera_status_payload(error=None, connected=None):
    payload = {
        'type': 'camera_status',
        'connected': bool(camera.is_running if connected is None else connected),
    }
    if error:
        payload['error'] = error
    return payload


def _submit_worker(fn):
    if _shutdown_event.is_set():
        return None
    try:
        future = executor.submit(fn)
    except RuntimeError:
        return None
    with _worker_futures_lock:
        _worker_futures.add(future)
    future.add_done_callback(lambda done: _discard_worker_future(done))
    return future


def _discard_worker_future(future):
    with _worker_futures_lock:
        _worker_futures.discard(future)


def _send_error(message_type, code, request_id=None):
    payload = {'type': message_type, 'success': False, 'error': code}
    if request_id is not None:
        payload['request_id'] = request_id
    ws_server.send_to_all(payload)


def _validate_lora_request(data):
    raw_master_name = data.get('master_name', '')
    if not isinstance(raw_master_name, str):
        raise ValueError('invalid_master_name')
    master_name = raw_master_name.strip()
    if not master_name or len(master_name) > 80 or any(ord(ch) < 32 for ch in master_name):
        raise ValueError('invalid_master_name')
    images = data.get('data')
    if not isinstance(images, list) or not (5 <= len(images) <= 100):
        raise ValueError('invalid_image_count')

    total_chars = 0
    normalized = []
    for item in images:
        if not isinstance(item, dict) or item.get('label') not in detector.EMOTIONS:
            raise ValueError('invalid_image_label')
        image = item.get('image')
        if not isinstance(image, str):
            raise ValueError('invalid_image_data')
        encoded = image.split(',', 1)[1] if ',' in image else image
        if not encoded or len(encoded) > 2_000_000:
            raise ValueError('image_too_large')
        total_chars += len(encoded)
        if total_chars > 20_000_000:
            raise ValueError('training_payload_too_large')
        normalized.append({'label': item['label'], 'image': encoded})
    return master_name, normalized


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

    if not isinstance(data, dict):
        _send_error('protocol_error', 'invalid_message')
        return
    msg_type = data.get('type')
    if not isinstance(msg_type, str):
        _send_error('protocol_error', 'invalid_message_type')
        return

    if msg_type == 'ping':
        ws_server.send_to_all({'type': 'pong', 'ts': time.time()})
        return

    if msg_type == 'get_camera_status':
        ws_server.send_to_all(_camera_status_payload())
        return

    if msg_type == 'start_focus':
        if focus_active:
            _send_error('focus_error', 'focus_already_active')
            return
        raw_duration = data.get('duration_minutes', 30)
        requested_duration = (
            raw_duration
            if isinstance(raw_duration, int) and not isinstance(raw_duration, bool)
            else 0
        )
        if not (1 <= requested_duration <= 1440):
            _send_error('focus_error', 'invalid_duration')
            return

        emotion_window.clear()
        care_popup_triggered = False

        logger.lang = current_lang
        try:
            logger.start_session(duration_minutes=requested_duration)
        except RuntimeError:
            _send_error('focus_error', 'focus_already_active')
            return
        focus_duration_mins = requested_duration
        focus_active = True
        focus_paused = False
        focus_start_time = time.time()
        focus_paused_seconds = 0.0
        _pause_started_at = None
        print(f"Backend: Focus started for {focus_duration_mins} minutes (lang={current_lang}).")

    elif msg_type == 'pause_focus':
        paused_value = data.get('paused', True)
        if not isinstance(paused_value, bool):
            _send_error('focus_error', 'invalid_paused_state')
            return
        if not focus_active:
            return
        want_pause = paused_value
        if want_pause and not focus_paused:
            logger.break_observation()
            focus_paused = True
            _pause_started_at = time.time()
            print("Backend: Focus paused.")
        elif not want_pause and focus_paused:
            _accumulate_pause()
            logger.break_observation()
            focus_paused = False
            print(f"Backend: Focus resumed (paused_total={focus_paused_seconds:.0f}s).")

    elif msg_type == 'end_focus':
        completed = data.get('completed', True)
        if not isinstance(completed, bool):
            _send_error('focus_error', 'invalid_completed_state')
            return
        if not focus_active:
            return

        if focus_paused:
            _accumulate_pause()
        focus_active = False
        focus_paused = False

        planned_mins = focus_duration_mins
        lang_snap = current_lang
        paused_snap = focus_paused_seconds
        session_snapshot = logger.detach_session()
        if session_snapshot is None:
            _send_error('focus_error', 'focus_session_missing')
            return
        stats = logger.stats_for_snapshot(session_snapshot)

        def _process_end_focus():
            comment = llm.get_focus_end_response(planned_mins, stats, lang=lang_snap)
            final_stats, actual_minutes, _ = logger.finalize_session(
                session_snapshot,
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

        _submit_worker(_process_end_focus)

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
        allowed_models = {
            'cnn', 'best_cnn.pth',
            'rnn', 'rnn_attention', 'best_rnn', 'best_rnn_attention.pth',
            'mobilenet', 'mobilenet_v2', 'best_mobilenet_v2.pth',
            'mock',
        }
        if mt not in allowed_models:
            _send_error('model_status', 'invalid_model')
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
        try:
            llm.reconfigure(base_url=base_url, api_key=api_key, model=model)
        except ValueError as exc:
            print(f"Backend: Rejected LLM configuration: {exc}")
            _send_error('llm_status', str(exc))
            return
        print(f"Backend: LLM reconfigured → {base_url} / {model}")
        ws_server.send_to_all({
            'type': 'llm_status',
            'base_url': llm.base_url,
            'model': llm.model,
            'has_key': bool(llm.api_key),
        })

    elif msg_type == 'toggle_camera':
        requested_state = data.get('state', True)
        if not isinstance(requested_state, bool):
            payload = _camera_status_payload('invalid_camera_state')
            payload['success'] = False
            ws_server.send_to_all(payload)
            return
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
        request_id = data.get('request_id')
        if request_id is not None:
            request_id = str(request_id)[:128]
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            _send_error('chat_reply', 'invalid_chat_text', request_id)
            return
        if hidden_context is not None and (
            not isinstance(hidden_context, str) or len(hidden_context) > 8000
        ):
            _send_error('chat_reply', 'invalid_hidden_context', request_id)
            return
        lang_snap = current_lang

        def _process_chat():
            try:
                reply = llm.chat_with_miku(text, hidden_context=hidden_context, lang=lang_snap)
                payload = {'type': 'chat_reply', 'text': reply}
            except Exception as exc:
                print(f"Backend: Chat request failed: {exc}")
                payload = {
                    'type': 'chat_reply',
                    'text': '',
                    'success': False,
                    'error': 'chat_failed',
                }
            if request_id is not None:
                payload['request_id'] = request_id
            ws_server.send_to_all(payload)
            print("Backend: Handled chat request")

        _submit_worker(_process_chat)

    elif msg_type == 'get_chat_history':
        ws_server.send_to_all({
            'type': 'chat_history_response',
            'history': llm.get_chat_history()
        })
        print("Backend: Sent chat history to frontend")

    elif msg_type == 'delete_lora_data':
        if not _lora_training_lock.acquire(blocking=False):
            _send_error('training_complete', 'training_in_progress')
            return
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
        finally:
            _lora_training_lock.release()

    elif msg_type == 'start_lora_training':
        try:
            master_name, images_data = _validate_lora_request(data)
        except ValueError as exc:
            _send_error('training_complete', str(exc))
            return
        if not _lora_training_lock.acquire(blocking=False):
            _send_error('training_complete', 'training_in_progress')
            return

        user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(os.path.dirname(__file__), '..', 'user')
        lora_dir = os.path.join(user_root, 'lora')
        try:
            os.makedirs(lora_dir, exist_ok=True)
        except OSError:
            _lora_training_lock.release()
            _send_error('training_complete', 'training_storage_unavailable')
            return
        camera_was_connected = camera.is_running
        if camera_was_connected:
            camera.stop()

        def _train_lora():
            import base64
            import numpy as np
            import cv2
            import io
            import torch
            import torch.nn as nn
            import torch.optim as optim
            from PIL import Image, UnidentifiedImageError
            from lora import inject_lora

            weights_tmp = os.path.join(lora_dir, 'lora_weights.pth.tmp')
            name_tmp = os.path.join(lora_dir, 'master_name.txt.tmp')
            try:
                print(f"Backend: Starting LoRA training for master {master_name} with {len(images_data)} images...")

                tensors = []
                targets = []

                for item in images_data:
                    if _shutdown_event.is_set():
                        raise RuntimeError('training_cancelled')
                    label = item['label']
                    try:
                        img_bytes = base64.b64decode(item['image'], validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError('invalid_image_encoding') from exc
                    if len(img_bytes) > 1_500_000:
                        raise ValueError('image_too_large')
                    try:
                        with Image.open(io.BytesIO(img_bytes)) as image:
                            width, height = image.size
                            if width > 2048 or height > 2048 or width * height > 4_000_000:
                                raise ValueError('image_dimensions_too_large')
                            image.verify()
                    except ValueError:
                        raise
                    except (UnidentifiedImageError, OSError) as exc:
                        raise ValueError('invalid_image_data') from exc
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if frame is None or frame.size == 0:
                        raise ValueError('invalid_image_data')
                    height, width = frame.shape[:2]
                    if width > 2048 or height > 2048 or width * height > 4_000_000:
                        raise ValueError('image_dimensions_too_large')

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
                    if _shutdown_event.is_set():
                        raise RuntimeError('training_cancelled')
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
                weights_path = os.path.join(lora_dir, 'lora_weights.pth')
                torch.save(lora_state, weights_tmp)
                os.replace(weights_tmp, weights_path)
                name_path = os.path.join(lora_dir, 'master_name.txt')
                with open(name_tmp, 'w', encoding='utf-8') as f:
                    f.write(master_name)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(name_tmp, name_path)
                print("Backend: LoRA weights saved successfully.")

                ws_server.send_to_all({"type": "training_complete", "success": True})
            except Exception as e:
                print(f"Backend: LoRA training failed: {e}")
                known_codes = {
                    'training_cancelled',
                    'invalid_image_encoding',
                    'image_too_large',
                    'invalid_image_data',
                    'image_dimensions_too_large',
                }
                error_code = str(e) if str(e) in known_codes else 'training_failed'
                ws_server.send_to_all({
                    "type": "training_complete",
                    "success": False,
                    "error": error_code,
                })
                if not _shutdown_event.is_set():
                    try:
                        detector.switch_model(detector.model_type, force=True)
                    except Exception as reload_error:
                        print(f"Backend: Failed to restore detector after training error: {reload_error}")
            finally:
                for tmp_path in (weights_tmp, name_tmp):
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except OSError:
                        pass
                try:
                    if detector.model is not None:
                        detector.model.eval()
                except Exception:
                    pass
                if camera_was_connected and not _shutdown_event.is_set():
                    camera.start()
                _lora_training_lock.release()

        # Run on infer executor so it doesn't race with detect_emotion
        try:
            infer_executor.submit(_train_lora)
        except RuntimeError:
            _lora_training_lock.release()
            if camera_was_connected and not _shutdown_event.is_set():
                camera.start()
            _send_error('training_complete', 'backend_stopping')


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
    if not care_popup_triggered and now >= care_cooldown_until:
        emotion_window.append((now, emotion))
        while emotion_window and now - emotion_window[0][0] > 30.0:
            emotion_window.popleft()

        covered_seconds = 0.0
        negative_seconds = 0.0
        for index in range(1, len(emotion_window)):
            previous_ts, previous_emotion = emotion_window[index - 1]
            current_ts, _ = emotion_window[index]
            elapsed = min(2.0, max(0.0, current_ts - previous_ts))
            covered_seconds += elapsed
            if previous_emotion in negative_emotions_set:
                negative_seconds += elapsed
        negative_ratio = negative_seconds / covered_seconds if covered_seconds else 0.0
        window_span = now - emotion_window[0][0] if emotion_window else 0.0
        if window_span >= 29.0 and covered_seconds >= 24.0 and negative_ratio >= 0.6:
            print(
                "Backend: Triggered proactive care popup "
                f"(negative={negative_seconds:.1f}s/{covered_seconds:.1f}s)"
            )
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

            _submit_worker(_trigger_care)

    if focus_active and not focus_paused:
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


def _backend_control_path():
    user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(
        os.path.dirname(__file__), '..', 'user'
    )
    return os.path.join(user_root, 'backend_control.json')


def _launcher_heartbeat_path():
    user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(
        os.path.dirname(__file__), '..', 'user'
    )
    return os.path.join(user_root, 'launcher_heartbeat.json')


def _read_valid_launcher_heartbeat(now_ms=None):
    """Read a bounded, signed launcher heartbeat for this launch session."""
    token = ws_server.auth_token
    launch_session = ws_server.launch_session
    if not token or not launch_session:
        return None
    path = _launcher_heartbeat_path()
    try:
        if os.path.getsize(path) > 16 * 1024:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return verify_launcher_heartbeat(
        data,
        token,
        launch_session,
        max_age_ms=int(LAUNCHER_HEARTBEAT_TIMEOUT_SEC * 1000),
        now_ms=now_ms,
    )


def _consume_signed_shutdown():
    """Accept only a fresh shutdown command signed for this launch session."""
    token = ws_server.auth_token
    launch_session = ws_server.launch_session
    if not token or not launch_session:
        return False
    path = _backend_control_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not verify_shutdown_command(data, token, launch_session):
            return False
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


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
    _protect_process_output()
    print("Miku Emotion Companion Backend Starting...")
    _write_pid_file()

    def on_client_connect():
        ws_server.send_to_all({
            "type": "backend_ready",
            "version": "1.2.0",
            "model": detector.model_type,
            "model_ready": detector.is_ready,
            "detector_error": detector.last_error,
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
            "version": "1.2.0",
            "model": detector.model_type,
            "model_ready": detector.is_ready,
            "detector_error": detector.last_error,
            "camera_enabled": bool(camera.is_running),
        })
        print("Backend: Ready signal broadcast.")
    else:
        print("Backend: Skipping ready broadcast (WebSocket not listening).")

    # Launcher-managed mode uses signed heartbeats because a Python shim can
    # remain alive while the real launcher is already gone. Direct Electron or
    # standalone launches retain the parent-PID watchdog.
    def _parent_watch():
        global is_running, _fast_exit_requested
        last_heartbeat_ts = 0
        last_valid_monotonic = time.monotonic()
        while is_running:
            if launcher_heartbeat_expected:
                now_ms = int(time.time() * 1000)
                heartbeat_ts = _read_valid_launcher_heartbeat(now_ms=now_ms)
                if heartbeat_ts is not None and heartbeat_ts > last_heartbeat_ts:
                    heartbeat_age = max(0.0, (now_ms - heartbeat_ts) / 1000.0)
                    last_valid_monotonic = time.monotonic() - heartbeat_age
                    last_heartbeat_ts = heartbeat_ts
                liveness_expired = (
                    time.monotonic() - last_valid_monotonic
                    > LAUNCHER_HEARTBEAT_TIMEOUT_SEC
                )
            else:
                liveness_expired = not _parent_alive()

            if liveness_expired:
                reason = (
                    "Signed launcher heartbeat expired"
                    if launcher_heartbeat_expected
                    else "Parent process gone"
                )
                _fast_exit_requested = True
                is_running = False
                print(f"Backend: {reason} - shutting down.")
                break

            time.sleep(
                LAUNCHER_HEARTBEAT_POLL_SEC
                if launcher_heartbeat_expected
                else 1.5
            )

    def _control_watch():
        global is_running, _fast_exit_requested
        while is_running:
            if _consume_signed_shutdown():
                _fast_exit_requested = True
                is_running = False
                print("Backend: Authenticated shutdown command received.")
                break
            time.sleep(0.2)

    threading.Thread(target=_parent_watch, daemon=True).start()
    threading.Thread(target=_control_watch, daemon=True).start()

    try:
        main_loop()
    except KeyboardInterrupt:
        print("Backend: Exiting on user interrupt...")
        _fast_exit_requested = True
    finally:
        is_running = False
        _shutdown_event.set()
        if _infer_future is not None:
            _infer_future.cancel()
        with _worker_futures_lock:
            for future in list(_worker_futures):
                future.cancel()
        try:
            llm.close(timeout=0.5)
        except Exception:
            pass
        camera.stop(timeout=1.0)
        ws_server.stop(timeout=1.0)
        infer_executor.shutdown(wait=False, cancel_futures=True)
        executor.shutdown(wait=False, cancel_futures=True)

        # Native MediaPipe close and a running inference must never hold a
        # launcher-requested shutdown hostage. Give idle cleanup a short window.
        detector_close_thread = None
        if _infer_future is None or _infer_future.done():
            detector_close_thread = threading.Thread(
                target=detector.close,
                name='miku-detector-close',
                daemon=True,
            )
            detector_close_thread.start()
            detector_close_thread.join(timeout=0.5)
        try:
            _clear_pid_file()
        except Exception:
            pass
        print("Miku Emotion Companion Backend Cleaned Up.")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        if _fast_exit_requested:
            os._exit(0)
