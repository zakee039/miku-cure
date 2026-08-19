import cv2
import threading
import time


class Camera:
    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(self, device_index=0, target_fps=1, status_callback=None):
        self.device_index = device_index
        self.target_fps = target_fps
        self.cap = None
        self.frame = None
        self.thread = None
        self.lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop_event = None
        self._generation = 0
        self._is_running = False
        self._status_callback = status_callback

    @property
    def is_running(self):
        with self._state_lock:
            return bool(
                self._is_running
                and self.thread is not None
                and self.thread.is_alive()
                and self.cap is not None
            )

    def set_status_callback(self, callback):
        with self._state_lock:
            self._status_callback = callback

    def _notify_status(self, connected, error=None):
        with self._state_lock:
            callback = self._status_callback
        if callback:
            try:
                callback(bool(connected), error)
            except Exception as exc:
                print(f"Camera: status callback failed: {exc}")

    def start(self):
        with self._state_lock:
            if self.is_running:
                return True
            if self.thread is not None and self.thread.is_alive():
                print("Camera: Previous capture thread is still stopping; restart refused.")
                return False

            cap = cv2.VideoCapture(self.device_index)
            if not cap.isOpened():
                cap.release()
                print(f"Error: Camera with device index {self.device_index} cannot be opened.")
                self._notify_status(False, 'camera_open_failed')
                return False

            # Prefer modest resolution for the low-FPS emotion pipeline.
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            self._generation += 1
            generation = self._generation
            stop_event = threading.Event()
            self._stop_event = stop_event
            self.cap = cap
            self._is_running = True
            start_gate = threading.Event()
            self.thread = threading.Thread(
                target=self._capture_loop,
                args=(cap, stop_event, generation, start_gate),
                name=f'miku-camera-{generation}',
                daemon=True,
            )
            self.thread.start()
        print("Camera thread started successfully.")
        self._notify_status(True)
        start_gate.set()
        return True

    def _capture_loop(self, cap, stop_event, generation, start_gate):
        delay = 1.0 / max(self.target_fps, 0.1)
        failures = 0
        disconnect_error = None
        try:
            start_gate.wait()
            while not stop_event.is_set():
                start_time = time.monotonic()
                ret, frame = cap.read()
                if stop_event.is_set():
                    break
                if ret and frame is not None:
                    failures = 0
                    owned = frame.copy()
                    with self.lock:
                        self.frame = owned
                else:
                    failures += 1
                    if failures == 1:
                        print("Warning: Camera failed to grab frame.")
                    if failures >= self.MAX_CONSECUTIVE_FAILURES:
                        disconnect_error = 'camera_read_failed'
                        print("Camera: Device stopped returning frames; marking disconnected.")
                        break

                sleep_time = delay - (time.monotonic() - start_time)
                if sleep_time > 0:
                    stop_event.wait(sleep_time)
        finally:
            try:
                cap.release()
            except Exception:
                pass
            should_notify = False
            with self._state_lock:
                if generation == self._generation:
                    self._is_running = False
                    if self.cap is cap:
                        self.cap = None
                    if self.thread is threading.current_thread():
                        self.thread = None
                    self._stop_event = None
                    should_notify = disconnect_error is not None
            with self.lock:
                self.frame = None
            if should_notify:
                self._notify_status(False, disconnect_error)

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

    def stop(self, timeout=2.0):
        with self._state_lock:
            thread = self.thread
            cap = self.cap
            event = self._stop_event
            was_running = self._is_running
            self._is_running = False
            if event:
                event.set()
        if cap:
            try:
                cap.release()
            except Exception:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        with self._state_lock:
            stopped = not (thread and thread.is_alive())
            if stopped:
                if self.thread is thread:
                    self.thread = None
                if self.cap is cap:
                    self.cap = None
                if self._stop_event is event:
                    self._stop_event = None
        with self.lock:
            self.frame = None
        if was_running:
            self._notify_status(False)
        if stopped:
            print("Camera thread stopped.")
        else:
            print(f"Camera: Capture thread did not stop within {timeout:.1f} seconds.")
        return stopped


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
