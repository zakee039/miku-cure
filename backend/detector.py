import os
import cv2
import numpy as np
import collections

# Try to import torch and mediapipe
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:
    torch = None

try:
    import mediapipe as mp
    try:
        from mediapipe.solutions import face_detection as mp_face_detection
    except (ImportError, ModuleNotFoundError):
        from mediapipe.python.solutions import face_detection as mp_face_detection
except (ImportError, ModuleNotFoundError):
    mp = None
    mp_face_detection = None

try:
    from models_def import EmotionCNN, GrayscaleMobileNetV2, RNNAttentionNetwork
    from lora import inject_lora
except ImportError:
    EmotionCNN = GrayscaleMobileNetV2 = RNNAttentionNetwork = None
    inject_lora = None

class EmotionDetector:
    EMOTIONS = ['neutral', 'happy', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt']

    def __init__(self, model_type='cnn', model_path=None):
        self.model_type = model_type
        # Safe device selection to prevent CUDA errors on unsupported GPUs (like RTX 5060 Blackwell)
        device_str = 'cpu'
        if torch and torch.cuda and torch.cuda.is_available():
            try:
                # Test if GPU works for EmotionCNN forward pass
                test_device = torch.device('cuda')
                test_model = EmotionCNN().to(test_device)
                test_input = torch.zeros(1, 1, 48, 48).to(test_device)
                with torch.no_grad():
                    _ = test_model(test_input)
                device_str = 'cuda'
                print("Detector: CUDA is available and working. Using GPU device.")
            except Exception as e:
                print(f"Detector: CUDA is available but test forward pass failed: {e}. Falling back to CPU.")
                device_str = 'cpu'
        else:
            print("Detector: CUDA not available. Using CPU device.")
            
        self.device = torch.device(device_str)
        self.model = None
        
        # Initialize MediaPipe face detector
        self.mp_face = None
        if mp_face_detection:
            try:
                self.mp_face = mp_face_detection.FaceDetection(
                    min_detection_confidence=0.5,
                    model_selection=0
                )
                print("Detector: MediaPipe face detection initialized successfully.")
            except Exception as e:
                print(f"Detector: MediaPipe initialization failed: {e}")
                self.mp_face = None
        else:
            print("Detector: MediaPipe is not installed or import failed. Face detection will fallback to raw OpenCV or whole frame.")

        # Initialize Haar Cascade face detector as fallback (with Windows unicode path workaround)
        self.face_cascade = None
        try:
            import shutil
            import tempfile
            xml_name = 'haarcascade_frontalface_default.xml'
            xml_src = os.path.join(cv2.data.haarcascades, xml_name)
            if os.path.exists(xml_src):
                temp_dir = tempfile.gettempdir()
                xml_dst = os.path.join(temp_dir, xml_name)
                shutil.copy(xml_src, xml_dst)
                self.face_cascade = cv2.CascadeClassifier(xml_dst)
                if not self.face_cascade.empty():
                    print(f"Detector: OpenCV Haar Cascade loaded successfully from temp: {xml_dst}")
                else:
                    self.face_cascade = None
            else:
                print("Detector: Haar Cascade XML source not found.")
        except Exception as e:
            print(f"Detector: Failed to initialize Haar Cascade fallback: {e}")

        # Attempt to load PyTorch custom model
        if torch and model_type not in ['deepface', 'mock'] and model_type:
            # Default path if none provided
            if not model_path:
                if model_type == 'cnn':
                    model_path = os.path.join(os.path.dirname(__file__), "models", "best_cnn.pth")
                else:
                    model_path = os.path.join(os.path.dirname(__file__), "models", model_type)
                
            if os.path.exists(model_path):
                try:
                    filename = os.path.basename(model_path).lower()
                    if 'mobilenet' in filename:
                        self.model = GrayscaleMobileNetV2().to(self.device)
                    elif 'rnn' in filename:
                        self.model = RNNAttentionNetwork().to(self.device)
                    else:
                        self.model = EmotionCNN().to(self.device)

                    self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                    # Apply LoRA if exists
                    lora_path = os.path.join(os.path.dirname(__file__), "..", "user", "lora", "lora_weights.pth")
                    if inject_lora and os.path.exists(lora_path):
                        self.model = inject_lora(self.model).to(self.device)
                        self.model.load_state_dict(torch.load(lora_path, map_location=self.device), strict=False)
                        print(f"Detector: Loaded LoRA weights from {lora_path}")
                    self.model.eval()
                    print(f"Detector: Loaded PyTorch model weights from {model_path} successfully on {self.device}")
                except Exception as e:
                    print(f"Detector: Failed to load PyTorch state dict: {e}")
                    self.model = None
            else:
                print(f"Detector: Model weights not found at {model_path}. Running in Demo/Fallback mode.")
                self.model = None

    def switch_model(self, model_type):
        """
        Dynamically switch model type at runtime.
        """
        if self.model_type == model_type:
            return
            
        print(f"Detector: Switching model type from '{self.model_type}' to '{model_type}'")
        self.model_type = model_type
        
        # Load weights if custom PyTorch model is selected
        if torch and model_type not in ['deepface', 'mock']:
            model_path = os.path.join(os.path.dirname(__file__), "models", model_type)
            # fallback to cnn logic if strictly 'cnn'
            if model_type == 'cnn':
                 model_path = os.path.join(os.path.dirname(__file__), "models", "best_cnn.pth")

            if os.path.exists(model_path):
                try:
                    filename = os.path.basename(model_path).lower()
                    if 'mobilenet' in filename:
                        self.model = GrayscaleMobileNetV2().to(self.device)
                    elif 'rnn' in filename:
                        self.model = RNNAttentionNetwork().to(self.device)
                    else:
                        self.model = EmotionCNN().to(self.device)

                    self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                    # Apply LoRA if exists
                    lora_path = os.path.join(os.path.dirname(__file__), "..", "user", "lora", "lora_weights.pth")
                    if inject_lora and os.path.exists(lora_path):
                        self.model = inject_lora(self.model).to(self.device)
                        self.model.load_state_dict(torch.load(lora_path, map_location=self.device), strict=False)
                        print(f"Detector: Loaded LoRA weights from {lora_path}")
                    self.model.eval()
                    print(f"Detector: Loaded PyTorch weights successfully on {self.device}")
                except Exception as e:
                    print(f"Detector: Failed to load PyTorch state dict: {e}")
                    self.model = None
            else:
                print(f"Detector: PyTorch weights not found at {model_path}. Running in fallback mode.")
                self.model = None
        else:
            # Clear loaded model if switching to mock/deepface
            self.model = None

    def detect_emotion(self, frame):
        """
        Takes raw BGR image frame from camera.
        Returns:
            smoothed_emotion: string (e.g. 'neutral')
            confidence: float (0 to 1)
            face_coords: tuple (x, y, w, h) of detected face in raw coordinates, or None
        """
        if frame is None:
            return 'no_face', 0.0, None
        face_img, face_coords = self.extract_face(frame)
        
        if face_img is None:
            return 'no_face', 0.0, None
        
        # 2. Run model inference if loaded
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
                detected_emotion, conf_val = self._fallback_inference(face_img)
        else:
            # Demo Fallback
            detected_emotion, conf_val = self._fallback_inference(face_img)

        if detected_emotion == 'sadness' and conf_val < 0.70:
            detected_emotion = 'neutral'

        return detected_emotion, conf_val, face_coords

    def extract_face(self, frame):
        if frame is None:
            return None, None
        h, w, _ = frame.shape
        face_img = None
        face_coords = None

        # 1. Detect face using MediaPipe
        if self.mp_face:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.mp_face.process(frame_rgb)
            if results.detections:
                # Take the first detected face
                detection = results.detections[0]
                bbox = detection.location_data.relative_bounding_box
                
                # Convert relative coordinates to pixels
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                width = int(bbox.width * w)
                height = int(bbox.height * h)
                
                # Add minor padding
                pad_x = int(width * 0.1)
                pad_y = int(height * 0.1)
                
                x_start = max(0, x - pad_x)
                y_start = max(0, y - pad_y)
                x_end = min(w, x + width + pad_x)
                y_end = min(h, y + height + pad_y)
                
                face_coords = (x_start, y_start, x_end - x_start, y_end - y_start)
                face_img = frame[y_start:y_end, x_start:x_end]
        
        # Fallback to OpenCV Haar Cascades if MediaPipe is missing or failed to detect
        if face_img is None or face_img.size == 0:
            if self.face_cascade is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
                if len(faces) > 0:
                    fx, fy, fw, fh = faces[0]
                    face_coords = (int(fx), int(fy), int(fw), int(fh))
                    face_img = frame[int(fy):int(fy+fh), int(fx):int(fx+fw)]

            # If no face is detected by any method, return None
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
        """
        DeepFace fallback or mock inference if custom weights are missing.
        """
        if self.model_type == 'deepface':
            try:
                from deepface import DeepFace
                import logging
                logging.getLogger("tensorflow").setLevel(logging.ERROR)
                
                res = DeepFace.analyze(face_img, actions=['emotion'], enforce_detection=False, silent=True)
                if isinstance(res, list):
                    res = res[0]
                dom_emotion = res.get('dominant_emotion', 'neutral')
                conf = res.get('emotion', {}).get(dom_emotion, 0.0) / 100.0
                return dom_emotion, conf
            except Exception as e:
                print(f"DeepFace fallback failed: {e}")
                # Fall through to mock if it fails

        # Fallback to simulated emotion detection based on brightness/mockup
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)
        # Simulated variance
        if mean_brightness > 135:
            return 'happy', 0.85
        elif mean_brightness < 90:
            return 'sadness', 0.75
        else:
            # Add some randomness for the mock to make it feel "active"
            import random
            rand_val = random.random()
            if rand_val > 0.8:
                return 'surprise', 0.60
            elif rand_val > 0.6:
                return 'neutral', 0.90
            else:
                return 'neutral', 0.85

if __name__ == '__main__':
    # Test Detector
    import time
    detector = EmotionDetector()
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    emotion, conf, bbox = detector.detect_emotion(dummy_frame)
    print(f"Mock Detection test -> Emotion: {emotion}, Conf: {conf:.2f}, Bbox: {bbox}")
