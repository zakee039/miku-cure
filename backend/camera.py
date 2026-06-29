import cv2
import threading
import time

class Camera:
    def __init__(self, device_index=0, target_fps=1):
        self.device_index = device_index
        self.target_fps = target_fps
        self.cap = None
        self.frame = None
        self.is_running = False
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        if self.is_running:
            return
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            print(f"Error: Camera with device index {self.device_index} cannot be opened.")
            return False
        
        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("Camera thread started successfully.")
        return True

    def _capture_loop(self):
        delay = 1.0 / self.target_fps
        while self.is_running:
            start_time = time.time()
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame.copy()
            else:
                print("Warning: Camera failed to grab frame.")
            
            elapsed = time.time() - start_time
            sleep_time = delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_frame(self):
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()
            return None

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        print("Camera thread stopped.")

if __name__ == '__main__':
    # Test Camera
    cam = Camera(target_fps=1)
    if cam.start():
        time.sleep(3)
        frame = cam.get_frame()
        if frame is not None:
            print(f"Success! Got frame of shape {frame.shape}")
        else:
            print("Failed to get frame.")
        cam.stop()
