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
            return True
        self.cap = cv2.VideoCapture(self.device_index)
        if not self.cap.isOpened():
            print(f"Error: Camera with device index {self.device_index} cannot be opened.")
            return False

        # Prefer modest resolution for 1 FPS emotion pipeline (less USB/CPU)
        try:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("Camera thread started successfully.")
        return True

    def _capture_loop(self):
        delay = 1.0 / max(self.target_fps, 0.1)
        while self.is_running:
            start_time = time.time()
            ret, frame = self.cap.read()
            if ret and frame is not None:
                # OpenCV reuses the capture buffer — must copy once here.
                # Consumers take ownership in get_frame() without a second copy.
                owned = frame.copy()
                with self.lock:
                    self.frame = owned
            else:
                # Don't spam logs every tick
                if int(start_time) % 5 == 0:
                    print("Warning: Camera failed to grab frame.")

            elapsed = time.time() - start_time
            sleep_time = delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_frame(self):
        """Return latest frame and clear buffer (single-copy handoff)."""
        with self.lock:
            frame = self.frame
            self.frame = None
            return frame

    def peek_frame(self):
        """Non-destructive read (copies) for rare multi-consumer cases."""
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
        with self.lock:
            self.frame = None
        print("Camera thread stopped.")


if __name__ == '__main__':
    cam = Camera(target_fps=1)
    if cam.start():
        time.sleep(2)
        frame = cam.get_frame()
        if frame is not None:
            print(f"Success! Got frame of shape {frame.shape}")
        else:
            print("Failed to get frame.")
        cam.stop()
