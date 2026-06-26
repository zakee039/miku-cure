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
    from mediapipe.python.solutions import face_detection as mp_face_detection
except ImportError:
    mp = None
    mp_face_detection = None

# 1. Define the PyTorch Custom CNN architecture (mirroring Keras notebook)
class EmotionCNN(nn.Module):
    def __init__(self, num_classes=8):
        super(EmotionCNN, self).__init__()
        
        # Block 1
        self.conv1_1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv1_2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.pool1 = nn.MaxPool2d(2, 2)
        self.drop1 = nn.Dropout(0.25)
        
        # Block 2
        self.conv2 = nn.Conv2d(64, 128, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm2d(128)
        self.pool2 = nn.MaxPool2d(2, 2)
        self.drop2 = nn.Dropout(0.25)
        
        # Block 3
        self.conv3 = nn.Conv2d(128, 512, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm2d(512)
        self.pool3 = nn.MaxPool2d(2, 2)
        self.drop3 = nn.Dropout(0.25)
        
        # Block 4
        self.conv4 = nn.Conv2d(512, 512, kernel_size=3, padding=1)
        self.bn4 = nn.BatchNorm2d(512)
        self.pool4 = nn.MaxPool2d(2, 2)
        self.drop4 = nn.Dropout(0.25)
        
        # Block 5
        self.conv5 = nn.Conv2d(512, 512, kernel_size=3, padding=1)
        self.bn5 = nn.BatchNorm2d(512)
        self.pool5 = nn.MaxPool2d(2, 2)
        self.drop5 = nn.Dropout(0.25)
        
        # Fully Connected Layers
        self.fc1 = nn.Linear(512 * 1 * 1, 256)
        self.bn_fc1 = nn.BatchNorm1d(256)
        self.drop_fc1 = nn.Dropout(0.25)
        
        self.fc2 = nn.Linear(256, 512)
        self.bn_fc2 = nn.BatchNorm1d(512)
        self.drop_fc2 = nn.Dropout(0.25)
        
        self.out = nn.Linear(512, num_classes)

    def forward(self, x):
        x = F.relu(self.conv1_1(x))
        x = F.relu(self.conv1_2(x))
        x = self.bn1(x)
        x = self.pool1(x)
        x = self.drop1(x)
        
        x = F.relu(self.conv2(x))
        x = self.bn2(x)
        x = self.pool2(x)
        x = self.drop2(x)
        
        x = F.relu(self.conv3(x))
        x = self.bn3(x)
        x = self.pool3(x)
        x = self.drop3(x)
        
        x = F.relu(self.conv4(x))
        x = self.bn4(x)
        x = self.pool4(x)
        x = self.drop4(x)
        
        x = F.relu(self.conv5(x))
        x = self.bn5(x)
        x = self.pool5(x)
        x = self.drop5(x)
        
        x = x.view(x.size(0), -1) # Flatten
        
        x = F.relu(self.fc1(x))
        x = self.bn_fc1(x)
        x = self.drop_fc1(x)
        
        x = F.relu(self.fc2(x))
        x = self.bn_fc2(x)
        x = self.drop_fc2(x)
        
        x = self.out(x)
        return x

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
        self.smoothing_queue = collections.deque(maxlen=5) # 5-frame voting smooth window
        
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

        # Attempt to load PyTorch custom CNN model
        if torch and model_type == 'cnn':
            self.model = EmotionCNN().to(self.device)
            # Default path if none provided
            if not model_path:
                model_path = os.path.join(os.path.dirname(__file__), "models", "best_cnn.pth")
                
            if os.path.exists(model_path):
                try:
                    self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                    self.model.eval()
                    print(f"Detector: Loaded custom CNN model weights from {model_path} successfully on {self.device}")
                except Exception as e:
                    print(f"Detector: Failed to load custom CNN state dict: {e}")
                    self.model = None
            else:
                print(f"Detector: Custom CNN model weights not found at {model_path}. Running in Demo/Fallback mode.")
                self.model = None

    def switch_model(self, model_type):
        """
        Dynamically switch model type at runtime.
        """
        if self.model_type == model_type:
            return
            
        print(f"Detector: Switching model type from '{self.model_type}' to '{model_type}'")
        self.model_type = model_type
        
        # Load weights if cnn is selected and not loaded
        if torch and model_type == 'cnn':
            if self.model is None:
                self.model = EmotionCNN().to(self.device)
            model_path = os.path.join(os.path.dirname(__file__), "models", "best_cnn.pth")
            if os.path.exists(model_path):
                try:
                    self.model.load_state_dict(torch.load(model_path, map_location=self.device))
                    self.model.eval()
                    print(f"Detector: Loaded custom CNN weights successfully on {self.device}")
                except Exception as e:
                    print(f"Detector: Failed to load custom CNN state dict: {e}")
                    self.model = None
            else:
                print(f"Detector: CNN weights not found at {model_path}. Running CNN in fallback mode.")
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
            return 'neutral', 1.0, None

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

            # If Haar Cascade is missing or failed to detect, crop center of frame
            if face_img is None or face_img.size == 0:
                cx, cy = w // 2, h // 2
                sz = min(w, h, 300) // 2
                face_coords = (cx - sz, cy - sz, sz * 2, sz * 2)
                face_img = frame[cy-sz:cy+sz, cx-sz:cx+sz]

        # 2. Run model inference if loaded
        if self.model and torch:
            try:
                # Preprocess face to grayscale 48x48
                gray_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
                resized_face = cv2.resize(gray_face, (48, 48))
                
                # Convert to tensor and standardize (normalization)
                tensor_face = torch.tensor(resized_face, dtype=torch.float32).unsqueeze(0).unsqueeze(0) # Shape: (1, 1, 48, 48)
                tensor_face = (tensor_face - 127.5) / 127.5 # Map to [-1, 1] range
                tensor_face = tensor_face.to(self.device)
                
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

        # 3. Add to sliding window smoothing queue
        self.smoothing_queue.append(detected_emotion)
        
        # Calculate majority vote
        counter = collections.Counter(self.smoothing_queue)
        smoothed_emotion = counter.most_common(1)[0][0]
        
        return smoothed_emotion, conf_val, face_coords

    def _fallback_inference(self, face_img):
        """
        DeepFace fallback or mock inference if custom weights are missing.
        """
        # Try DeepFace out-of-the-box facial attribute analyzer
        try:
            from deepface import DeepFace
            # Disable logger outputs
            import logging
            logging.getLogger("tensorflow").setLevel(logging.ERROR)
            
            # DeepFace analyze BGR image
            result = DeepFace.analyze(face_img, actions=['emotion'], enforce_detection=False, silent=True)
            if isinstance(result, list):
                result = result[0]
            
            dominant_emotion = result['dominant_emotion']
            # Map deepface emotions ('angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral')
            mapping = {
                'sad': 'sadness',
                'happy': 'happy',
                'angry': 'anger',
                'fear': 'fear',
                'disgust': 'disgust',
                'surprise': 'surprise',
                'neutral': 'neutral'
            }
            emotion = mapping.get(dominant_emotion, 'neutral')
            # Extract emotion scores
            scores = result['emotion']
            max_score = scores.get(dominant_emotion, 100.0) / 100.0
            return emotion, max_score
        except Exception as e:
            # Fallback to simulated emotion detection based on brightness/mockup
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
            mean_brightness = np.mean(gray)
            # Simulated variance
            if mean_brightness > 135:
                return 'happy', 0.85
            elif mean_brightness < 90:
                return 'sadness', 0.75
            else:
                return 'neutral', 0.90

if __name__ == '__main__':
    # Test Detector
    import time
    detector = EmotionDetector()
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    emotion, conf, bbox = detector.detect_emotion(dummy_frame)
    print(f"Mock Detection test -> Emotion: {emotion}, Conf: {conf:.2f}, Bbox: {bbox}")
