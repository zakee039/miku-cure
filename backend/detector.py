import os
import cv2
import numpy as np
import collections
import copy

# Keep the desktop companion offline. Some MediaPipe builds honor this flag;
# native task objects are also closed explicitly during backend shutdown.
os.environ.setdefault('MEDIAPIPE_DISABLE_TELEMETRY', '1')

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:
    torch = None

try:
    import mediapipe as mp
except (ImportError, ModuleNotFoundError):
    mp = None

# Legacy solutions API (removed in newer mediapipe builds)
mp_face_detection_legacy = None
if mp is not None:
    try:
        from mediapipe.solutions import face_detection as mp_face_detection_legacy
    except (ImportError, ModuleNotFoundError):
        try:
            from mediapipe.python.solutions import face_detection as mp_face_detection_legacy
        except (ImportError, ModuleNotFoundError):
            mp_face_detection_legacy = None

try:
    from models_def import EmotionCNN, GrayscaleMobileNetV2, RNNAttentionNetwork
    from lora import inject_lora
except ImportError:
    EmotionCNN = GrayscaleMobileNetV2 = RNNAttentionNetwork = None
    inject_lora = None

# MediaPipe Tasks FaceDetector model (auto-downloaded on first use)
_BLAZE_FACE_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
_BLAZE_FACE_NAME = "blaze_face_short_range.tflite"


def _ascii_model_cache_dir():
    """
    MediaPipe's C++ loader on Windows often fails on non-ASCII paths
    (e.g. project folders with Chinese names). Prefer LOCALAPPDATA.
    """
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('TEMP') or os.path.expanduser('~')
    # Guard: if still non-ascii, fall back to temp short path
    try:
        base.encode('ascii')
    except UnicodeEncodeError:
        base = os.environ.get('TEMP') or r'C:\Temp'
    path = os.path.join(base, 'miku-cure', 'models')
    os.makedirs(path, exist_ok=True)
    return path


def _ensure_blaze_face_model():
    """
    Return a model path that MediaPipe can open.
    Seed from backend/models/ if present; always serve from ASCII cache.
    """
    import shutil
    cache_path = os.path.join(_ascii_model_cache_dir(), _BLAZE_FACE_NAME)
    project_path = os.path.join(os.path.dirname(__file__), "models", _BLAZE_FACE_NAME)

    def _ok(p):
        return os.path.exists(p) and os.path.getsize(p) > 10_000

    if _ok(cache_path):
        return cache_path

    # Copy from project tree if available (may contain non-ascii parent dirs)
    if _ok(project_path):
        try:
            shutil.copy2(project_path, cache_path)
            if _ok(cache_path):
                print(f"Detector: Copied BlazeFace model to ASCII cache: {cache_path}")
                return cache_path
        except Exception as e:
            print(f"Detector: Failed to copy model to cache: {e}")

    print(f"Detector: Downloading MediaPipe BlazeFace model → {cache_path}")
    try:
        import urllib.request
        urllib.request.urlretrieve(_BLAZE_FACE_URL, cache_path)
        # Also keep a project-local copy for offline packaging when path allows
        try:
            os.makedirs(os.path.dirname(project_path), exist_ok=True)
            if not _ok(project_path):
                shutil.copy2(cache_path, project_path)
        except Exception:
            pass
        print("Detector: BlazeFace model downloaded.")
        return cache_path
    except Exception as e:
        print(f"Detector: Failed to download BlazeFace model: {e}")
        return None


def _create_mp_tasks_face_detector(force=False):
    """Create the production MediaPipe detector unless Haar is explicitly selected."""
    selected = os.environ.get('MIKU_FACE_DETECTOR', 'mediapipe').strip().lower()
    if not force and selected not in ('mediapipe', 'mp_tasks'):
        return None
    if mp is None:
        return None
    try:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except (ImportError, ModuleNotFoundError) as e:
        print(f"Detector: MediaPipe Tasks not available: {e}")
        return None

    model_path = _ensure_blaze_face_model()
    if not model_path:
        return None
    try:
        options = mp_vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=mp_vision.RunningMode.IMAGE,
            min_detection_confidence=0.5,
        )
        detector = mp_vision.FaceDetector.create_from_options(options)
        print("Detector: MediaPipe Tasks FaceDetector initialized.")
        return detector
    except Exception as e:
        print(f"Detector: MediaPipe Tasks FaceDetector init failed: {e}")
        return None


def _load_haar_cascade():
    """Load Haar from memory so Unicode paths and temp-file races are irrelevant."""
    xml_name = 'haarcascade_frontalface_default.xml'
    xml_src = os.path.join(cv2.data.haarcascades, xml_name)
    if not os.path.isfile(xml_src):
        print("Detector: Haar Cascade XML source not found.")
        return None

    storage = None
    try:
        with open(xml_src, 'r', encoding='utf-8') as f:
            xml_data = f.read()
        storage = cv2.FileStorage(
            xml_data,
            cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY,
        )
        cascade = cv2.CascadeClassifier()
        node = storage.getFirstTopLevelNode()
        if node.empty() or not cascade.read(node) or cascade.empty():
            return None
        return cascade
    except (OSError, cv2.error) as e:
        print(f"Detector: Haar Cascade load failed: {e}")
        return None
    finally:
        if storage is not None:
            storage.release()

def _select_device():
    """Lightweight CUDA probe — avoids constructing a full EmotionCNN."""
    if not torch or not torch.cuda or not torch.cuda.is_available():
        print("Detector: CUDA not available. Using CPU device.")
        return torch.device('cpu') if torch else None
    try:
        t = torch.zeros(1, device='cuda')
        _ = t + 1
        del t
        if hasattr(torch.cuda, 'empty_cache'):
            torch.cuda.empty_cache()
        print("Detector: CUDA is available and working. Using GPU device.")
        return torch.device('cuda')
    except Exception as e:
        print(f"Detector: CUDA probe failed: {e}. Falling back to CPU.")
        return torch.device('cpu')


class EmotionDetector:
    EMOTIONS = ['neutral', 'happy', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt']

    def __init__(self, model_type='best_rnn_attention.pth', model_path=None, smooth_window=1, conf_threshold=0.0):
        self.model_type = model_type
        self.device = _select_device()
        self.model = None
        self.last_error = None
        self.mock_mode = model_type == 'mock'
        # smooth_window kept for API compat; smoothing is disabled (real-time raw labels)
        self.smooth_window = max(1, smooth_window)
        self.conf_threshold = conf_threshold
        self._emotion_history = collections.deque(maxlen=self.smooth_window)
        self._last_stable = ('neutral', 0.0)

        # Face detectors: prefer Tasks API → legacy solutions → Haar
        selected_face_detector = os.environ.get('MIKU_FACE_DETECTOR', 'mediapipe').strip().lower()
        mediapipe_enabled = selected_face_detector in ('mediapipe', 'mp_tasks')
        self.mp_tasks_face = _create_mp_tasks_face_detector()
        self.mp_face = None  # legacy solutions FaceDetection
        if (
            mediapipe_enabled
            and self.mp_tasks_face is None
            and mp_face_detection_legacy is not None
        ):
            try:
                self.mp_face = mp_face_detection_legacy.FaceDetection(
                    min_detection_confidence=0.5,
                    model_selection=0,
                )
                print("Detector: MediaPipe legacy solutions FaceDetection initialized.")
            except Exception as e:
                print(f"Detector: MediaPipe legacy init failed: {e}")
                self.mp_face = None
        if self.mp_tasks_face is None and self.mp_face is None:
            if not mediapipe_enabled:
                print("Detector: Using offline OpenCV Haar face detector.")
            elif mp is None:
                print("Detector: MediaPipe not installed — using Haar fallback.")
            else:
                print("Detector: MediaPipe face detector unavailable — using Haar fallback.")

        self.face_cascade = None
        try:
            self.face_cascade = _load_haar_cascade()
            if self.face_cascade is not None:
                print("Detector: OpenCV Haar Cascade loaded from memory.")
            else:
                print("Detector: OpenCV Haar Cascade could not be loaded.")
        except Exception as e:
            print(f"Detector: Failed to initialize Haar Cascade fallback: {e}")

        if torch and model_type not in ['mock'] and model_type:
            self._load_model(model_type, model_path)

    def _resolve_model_path(self, model_type, model_path=None):
        if model_path:
            return model_path
        models_dir = os.path.join(os.path.dirname(__file__), "models")
        if model_type == 'cnn':
            return os.path.join(models_dir, "best_cnn.pth")
        # Allow full filename (e.g. best_rnn_attention.pth) or bare type
        candidate = os.path.join(models_dir, model_type)
        if os.path.exists(candidate):
            return candidate
        # Common aliases
        aliases = {
            'rnn': 'best_rnn_attention.pth',
            'rnn_attention': 'best_rnn_attention.pth',
            'best_rnn': 'best_rnn_attention.pth',
            'mobilenet': 'best_mobilenet_v2.pth',
            'mobilenet_v2': 'best_mobilenet_v2.pth',
        }
        if model_type in aliases:
            return os.path.join(models_dir, aliases[model_type])
        return candidate

    def _build_architecture(self, model_path):
        filename = os.path.basename(model_path).lower()
        if 'mobilenet' in filename:
            return GrayscaleMobileNetV2(pretrained=False).to(self.device)
        if 'rnn' in filename:
            return RNNAttentionNetwork().to(self.device)
        return EmotionCNN().to(self.device)

    def _apply_lora(self):
        user_root = os.environ.get('MIKU_USER_DIR') or os.path.join(
            os.path.dirname(__file__), "..", "user"
        )
        lora_path = os.path.join(user_root, "lora", "lora_weights.pth")
        if inject_lora and os.path.exists(lora_path):
            try:
                state = torch.load(lora_path, map_location=self.device, weights_only=True)
            except TypeError:
                raise
            except Exception as exc:
                print(f"Detector: Ignoring invalid LoRA weights: {exc}")
                return
            try:
                candidate = inject_lora(copy.deepcopy(self.model)).to(self.device)
                candidate.load_state_dict(state, strict=False)
                self.model = candidate
                print(f"Detector: Loaded LoRA weights from {lora_path}")
            except Exception as exc:
                print(f"Detector: LoRA weights are incompatible and were ignored: {exc}")

    def _load_model(self, model_type, model_path=None):
        """Shared model load path for init and hot-switch."""
        if not torch:
            self.model = None
            self.last_error = 'torch_unavailable'
            return
        path = self._resolve_model_path(model_type, model_path)
        if not os.path.exists(path):
            print(f"Detector: Model weights not found at {path}. Emotion inference disabled.")
            self.model = None
            self.last_error = 'model_weights_missing'
            return
        try:
            self.model = self._build_architecture(path)
            state = torch.load(path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            self._apply_lora()
            self.model.eval()
            self.last_error = None
            print(f"Detector: Loaded PyTorch model from {path} on {self.device}")
        except TypeError:
            print(
                "Detector: This PyTorch version lacks safe weights_only loading. "
                "Upgrade PyTorch; unsafe pickle fallback is disabled."
            )
            self.model = None
            self.last_error = 'unsafe_torch_version'
        except Exception as e:
            print(f"Detector: Failed to load PyTorch state dict: {e}")
            self.model = None
            self.last_error = 'model_load_failed'

    def switch_model(self, model_type, force=False):
        """
        Hot-swap inference engine. Skips reload when type unchanged unless force=True
        (used after LoRA delete / retrain).
        """
        if (
            not force
            and self.model_type == model_type
            and model_type not in ('mock',)
            and self.model is not None
        ):
            return

        print(f"Detector: Switching model type from '{self.model_type}' to '{model_type}' (force={force})")
        self.model_type = model_type
        self.mock_mode = model_type == 'mock'
        self._emotion_history.clear()

        if torch and model_type not in ['mock']:
            self._load_model(model_type)
        else:
            self.model = None

    def detect_emotion(self, frame):
        """
        Real-time raw prediction (no temporal smoothing).
        Returns:
            emotion: string
            confidence: float
            face_coords: (x, y, w, h) or None
        """
        if frame is None:
            return 'no_face', 0.0, None

        face_img, face_coords = self.extract_face(frame)
        if face_img is None:
            return 'no_face', 0.0, None

        if self.model and torch:
            try:
                tensor_face = self.preprocess_to_tensor(face_img)
                with torch.no_grad():
                    outputs = self.model(tensor_face)
                    probs = F.softmax(outputs, dim=1)
                    confidence, class_idx = torch.max(probs, dim=1)
                    detected_emotion = self.EMOTIONS[class_idx.item()]
                    conf_val = confidence.item()
            except Exception as e:
                print(f"Detector: Model forward pass failed: {e}")
                self.last_error = 'model_inference_failed'
                return 'no_face', 0.0, face_coords
        elif self.mock_mode:
            detected_emotion, conf_val = self._fallback_inference(face_img)
        else:
            return 'no_face', 0.0, face_coords

        return detected_emotion, conf_val, face_coords

    def _crop_padded(self, frame, x, y, width, height):
        h, w = frame.shape[:2]
        pad_x = int(width * 0.1)
        pad_y = int(height * 0.1)
        x_start = max(0, int(x) - pad_x)
        y_start = max(0, int(y) - pad_y)
        x_end = min(w, int(x + width) + pad_x)
        y_end = min(h, int(y + height) + pad_y)
        if x_end <= x_start or y_end <= y_start:
            return None, None
        coords = (x_start, y_start, x_end - x_start, y_end - y_start)
        return frame[y_start:y_end, x_start:x_end], coords

    def extract_face(self, frame):
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        face_img = None
        face_coords = None

        # 1) MediaPipe Tasks API
        if self.mp_tasks_face is not None and mp is not None:
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Contiguous buffer required by mp.Image
                frame_rgb = np.ascontiguousarray(frame_rgb)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                result = self.mp_tasks_face.detect(mp_image)
                if result and result.detections:
                    det = result.detections[0]
                    box = det.bounding_box  # absolute pixel coords
                    face_img, face_coords = self._crop_padded(
                        frame, box.origin_x, box.origin_y, box.width, box.height
                    )
            except Exception as e:
                print(f"Detector: MediaPipe Tasks detect failed: {e}")

        # 2) Legacy solutions API
        if (face_img is None or face_img.size == 0) and self.mp_face is not None:
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.mp_face.process(frame_rgb)
                if results.detections:
                    detection = results.detections[0]
                    bbox = detection.location_data.relative_bounding_box
                    x = int(bbox.xmin * w)
                    y = int(bbox.ymin * h)
                    width = int(bbox.width * w)
                    height = int(bbox.height * h)
                    face_img, face_coords = self._crop_padded(frame, x, y, width, height)
            except Exception as e:
                print(f"Detector: MediaPipe legacy detect failed: {e}")

        # 3) Haar cascade
        if face_img is None or face_img.size == 0:
            if self.face_cascade is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
                if len(faces) > 0:
                    fx, fy, fw, fh = faces[0]
                    face_coords = (int(fx), int(fy), int(fw), int(fh))
                    face_img = frame[int(fy):int(fy + fh), int(fx):int(fx + fw)]

            if face_img is None or face_img.size == 0:
                return None, None
        return face_img, face_coords

    def preprocess_to_tensor(self, face_img):
        gray_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        resized_face = cv2.resize(gray_face, (48, 48))
        tensor_face = torch.tensor(resized_face, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
        tensor_face = (tensor_face - 127.5) / 127.5
        return tensor_face.to(self.device)

    def _fallback_inference(self, face_img):
        """Deterministic brightness mock, only for explicit model_type='mock'."""
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)
        if mean_brightness > 135:
            return 'happy', 0.85
        if mean_brightness < 90:
            return 'sadness', 0.75
        return 'neutral', 0.65

    @property
    def is_ready(self):
        return bool(self.mock_mode or (self.model is not None and self.last_error is None))

    def close(self):
        """Release native MediaPipe resources before interpreter teardown."""
        for attr in ('mp_tasks_face', 'mp_face'):
            resource = getattr(self, attr, None)
            close = getattr(resource, 'close', None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    print(f"Detector: Failed to close {attr}: {exc}")
            setattr(self, attr, None)


if __name__ == '__main__':
    detector = EmotionDetector()
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    emotion, conf, bbox = detector.detect_emotion(dummy_frame)
    print(f"Mock Detection test -> Emotion: {emotion}, Conf: {conf:.2f}, Bbox: {bbox}")
