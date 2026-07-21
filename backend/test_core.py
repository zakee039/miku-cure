"""Unit + light integration tests for Miku Cure backend.

Run: python test_core.py
"""
import os
import sys
import tempfile
import shutil
import unittest
import time
import json
import asyncio

sys.path.insert(0, os.path.dirname(__file__))

from logger import EmotionLogger


class TestEmotionLogger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.logger = EmotionLogger(log_dir=self.tmp, flush_interval_sec=999)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skip_no_face(self):
        self.logger.start_session(1)
        self.logger.log_emotion('no_face', 0.0)
        self.logger.log_emotion('happy', 0.9)
        self.assertEqual(len(self.logger.current_session_entries), 1)
        self.assertEqual(self.logger.current_session_entries[0].emotion, 'happy')

    def test_merge_same_emotion(self):
        self.logger.start_session(1)
        self.logger.log_emotion('neutral', 0.8)
        self.logger.log_emotion('neutral', 0.9)
        self.assertEqual(len(self.logger.current_session_entries), 1)
        self.assertEqual(self.logger.current_session_entries[0].duration, 2)

    def test_contempt_in_stats(self):
        self.logger.start_session(1)
        self.logger.log_emotion('contempt', 0.7)
        stats, _ = self.logger.end_session(miku_comment='ok')
        self.assertIn('contempt', stats)
        self.assertGreater(stats['contempt'], 0)

    def test_end_session_empty(self):
        stats, mins = self.logger.end_session()
        self.assertEqual(stats, {})
        self.assertEqual(mins, 0)

    def test_flush_throttle_marks_dirty(self):
        self.logger.start_session(1)
        self.logger.log_emotion('happy', 0.9)
        self.assertTrue(self.logger._dirty)
        self.logger._write_file()
        self.assertFalse(self.logger._dirty)


class TestDetectorRealtime(unittest.TestCase):
    def test_raw_no_face(self):
        from detector import EmotionDetector
        det = EmotionDetector.__new__(EmotionDetector)
        det.model = None
        det.model_type = 'mock'
        det.mp_tasks_face = None
        det.mp_face = None
        det.face_cascade = None
        em, conf, bb = EmotionDetector.detect_emotion(det, None)
        self.assertEqual(em, 'no_face')
        self.assertEqual(conf, 0.0)


class TestModelsDef(unittest.TestCase):
    def test_cnn_forward_shape(self):
        try:
            import torch
            from models_def import EmotionCNN
        except ImportError:
            self.skipTest('torch not installed')
        m = EmotionCNN()
        m.eval()
        x = torch.zeros(2, 1, 48, 48)
        y = m(x)
        self.assertEqual(tuple(y.shape), (2, 8))

    def test_mobilenet_no_pretrained_construct(self):
        try:
            import torch
            from models_def import GrayscaleMobileNetV2
        except ImportError:
            self.skipTest('torch not installed')
        m = GrayscaleMobileNetV2(pretrained=False)
        m.eval()
        x = torch.zeros(1, 1, 48, 48)
        y = m(x)
        self.assertEqual(tuple(y.shape), (1, 8))

    def test_lora_inject(self):
        try:
            import torch
            from models_def import EmotionCNN
            from lora import inject_lora
        except ImportError:
            self.skipTest('torch not installed')
        m = inject_lora(EmotionCNN())
        m.eval()
        y = m(torch.zeros(1, 1, 48, 48))
        self.assertEqual(tuple(y.shape), (1, 8))
        names = [n for n, _ in m.named_parameters() if 'lora_' in n]
        self.assertGreaterEqual(len(names), 2)


class TestWebSocketCleanStop(unittest.TestCase):
    def test_ready_and_stop(self):
        from websocket_server import MikuWebSocketServer
        import websockets

        received = []
        srv = MikuWebSocketServer(host='127.0.0.1', port=18766)
        srv.start(lambda d: received.append(d))
        time.sleep(0.35)

        async def client():
            async with websockets.connect(f'ws://127.0.0.1:{srv.port or 18766}') as ws:
                ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                await ws.send(json.dumps({'type': 'ping'}))
                await asyncio.sleep(0.15)
                return ready

        ready = asyncio.run(client())
        self.assertEqual(ready.get('type'), 'backend_ready')
        self.assertTrue(any(m.get('type') == 'ping' for m in received))
        srv.stop()
        time.sleep(0.2)


class TestCameraHandoff(unittest.TestCase):
    def test_get_frame_clears_buffer(self):
        from camera import Camera
        import numpy as np

        cam = Camera(device_index=0, target_fps=5)
        fake = np.zeros((48, 48, 3), dtype=np.uint8)
        with cam.lock:
            cam.frame = fake
        got = cam.get_frame()
        self.assertIsNotNone(got)
        self.assertIsNone(cam.get_frame())
        self.assertEqual(got.shape, (48, 48, 3))


if __name__ == '__main__':
    unittest.main(verbosity=2)
