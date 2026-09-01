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
import threading
import subprocess
import hashlib
from types import SimpleNamespace
from unittest import mock

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
        self.logger.log_emotion('neutral', 0.8, observed_at=100.0)
        self.logger.log_emotion('neutral', 0.9, observed_at=100.5)
        self.assertEqual(len(self.logger.current_session_entries), 1)
        self.assertAlmostEqual(self.logger.current_session_entries[0].duration, 0.5)

    def test_no_face_breaks_wall_clock_segment(self):
        self.logger.start_session(1)
        self.logger.log_emotion('happy', 0.9, observed_at=100.0)
        self.logger.log_emotion('no_face', 0.0, observed_at=100.5)
        self.logger.log_emotion('happy', 0.8, observed_at=110.0)
        self.assertAlmostEqual(self.logger.current_session_entries[0].duration, 0.5)

    def test_detached_session_cannot_clear_new_session(self):
        self.logger.start_session(1)
        first_path = self.logger.log_file
        self.logger.log_emotion('happy', 0.9, observed_at=100.0)
        snapshot = self.logger.detach_session()
        self.logger.start_session(2)
        second_path = self.logger.log_file
        self.logger.log_emotion('neutral', 0.8, observed_at=200.0)
        self.logger.finalize_session(snapshot, miku_comment='old')
        self.assertIsNotNone(self.logger.session_start_time)
        self.assertEqual(self.logger.current_session_entries[-1].emotion, 'neutral')
        self.assertNotEqual(first_path, second_path)

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
    def test_production_default_prefers_mediapipe(self):
        import detector as detector_module

        old = os.environ.pop('MIKU_FACE_DETECTOR', None)
        try:
            fake_tasks = SimpleNamespace(close=lambda: None)
            with (
                mock.patch.object(
                    detector_module,
                    '_create_mp_tasks_face_detector',
                    return_value=fake_tasks,
                ) as create_tasks,
                mock.patch.object(detector_module, '_load_haar_cascade', return_value=None),
            ):
                det = detector_module.EmotionDetector(model_type='mock')
            self.assertIs(det.mp_tasks_face, fake_tasks)
            create_tasks.assert_called_once_with()
        finally:
            if old is not None:
                os.environ['MIKU_FACE_DETECTOR'] = old

    def test_haar_cascade_load_is_parallel_safe_from_unicode_project_path(self):
        from concurrent.futures import ThreadPoolExecutor
        from detector import _load_haar_cascade

        with ThreadPoolExecutor(max_workers=4) as pool:
            cascades = list(pool.map(lambda _: _load_haar_cascade(), range(8)))
        self.assertTrue(all(item is not None and not item.empty() for item in cascades))

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

    def test_missing_production_model_never_fabricates_emotion(self):
        from detector import EmotionDetector
        import numpy as np
        det = EmotionDetector.__new__(EmotionDetector)
        det.model = None
        det.mock_mode = False
        det.extract_face = lambda frame: (np.ones((48, 48, 3), dtype=np.uint8), (0, 0, 48, 48))
        em, conf, _ = EmotionDetector.detect_emotion(det, np.ones((48, 48, 3), dtype=np.uint8))
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
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_user_dir = os.environ.get('MIKU_USER_DIR')
        os.environ['MIKU_USER_DIR'] = self.tmp

    def tearDown(self):
        if self.old_user_dir is None:
            os.environ.pop('MIKU_USER_DIR', None)
        else:
            os.environ['MIKU_USER_DIR'] = self.old_user_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ready_and_stop(self):
        from websocket_server import MikuWebSocketServer
        import websockets

        received = []
        token = 'unit-test-ws-token'
        srv = MikuWebSocketServer(
            host='127.0.0.1', port=18766, auth_token=token, launch_session='test-session'
        )
        srv.start(lambda d: received.append(d))
        time.sleep(0.35)

        async def client():
            async with websockets.connect(f'ws://127.0.0.1:{srv.port or 18766}') as ws:
                await ws.send(json.dumps({'type': 'authenticate', 'token': token}))
                authenticated = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                await ws.send(json.dumps({'type': 'ping'}))
                await asyncio.sleep(0.15)
                return authenticated, ready

        authenticated, ready = asyncio.run(client())
        self.assertTrue(authenticated.get('ok'))
        self.assertEqual(ready.get('type'), 'backend_ready')
        self.assertTrue(any(m.get('type') == 'ping' for m in received))
        srv.stop()
        time.sleep(0.2)

    def test_unauthenticated_message_never_reaches_callback(self):
        from websocket_server import MikuWebSocketServer
        import websockets

        received = []
        srv = MikuWebSocketServer(
            host='127.0.0.1', port=18768, auth_token='right-token-12345', launch_session='session'
        )
        srv.start(lambda data: received.append(data))
        time.sleep(0.25)

        async def client():
            async with websockets.connect('ws://127.0.0.1:18768') as ws:
                await ws.send(json.dumps({'type': 'ping'}))
                with self.assertRaises(websockets.exceptions.ConnectionClosed):
                    await ws.recv()

        try:
            asyncio.run(client())
            self.assertEqual(received, [])
        finally:
            srv.stop()


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

    def test_read_failure_marks_camera_disconnected(self):
        from camera import Camera

        class BrokenCapture:
            def isOpened(self):
                return True

            def set(self, *args):
                return True

            def read(self):
                return False, None

            def release(self):
                pass

        statuses = []
        cam = Camera(device_index=0, target_fps=100, status_callback=lambda state, error=None: statuses.append((state, error)))
        with mock.patch('camera.cv2.VideoCapture', return_value=BrokenCapture()):
            self.assertTrue(cam.start())
            deadline = time.time() + 1.0
            while cam.is_running and time.time() < deadline:
                time.sleep(0.02)
        self.assertFalse(cam.is_running)
        self.assertIn((False, 'camera_read_failed'), statuses)

    def test_snapshot_is_non_destructive_and_cursor_based(self):
        from camera import Camera
        import numpy as np

        cam = Camera(device_index=0, target_fps=5)
        fake = np.ones((24, 24, 3), dtype=np.uint8)
        with cam.lock:
            cam.frame = fake
            cam.frame_sequence = 7
            cam.frame_captured_at = 12.5
        first = cam.get_snapshot(0)
        second = cam.get_snapshot(0)
        self.assertEqual(first.sequence, 7)
        self.assertEqual(first.captured_at, 12.5)
        self.assertIsNot(first.image, second.image)
        self.assertIsNone(cam.get_snapshot(7))
        self.assertEqual(cam.set_target_fps(120), 60.0)


class TestFaceTracker(unittest.TestCase):
    def test_semantic_blendshape_mapping(self):
        import numpy as np
        from face_tracker import FaceTracker

        categories = [
            SimpleNamespace(category_name='eyeBlinkLeft', score=0.25),
            SimpleNamespace(category_name='eyeBlinkRight', score=0.5),
            SimpleNamespace(category_name='mouthSmileLeft', score=0.8),
            SimpleNamespace(category_name='mouthSmileRight', score=0.6),
            SimpleNamespace(category_name='jawOpen', score=0.4),
            SimpleNamespace(category_name='cheekPuff', score=0.3),
        ]
        result = SimpleNamespace(
            face_landmarks=[[SimpleNamespace(x=0.5, y=0.5, z=0.0)]],
            face_blendshapes=[categories],
            facial_transformation_matrixes=[np.eye(4)],
        )
        payload = FaceTracker('unused')._to_semantic_payload(result)
        self.assertTrue(payload['valid'])
        self.assertAlmostEqual(payload['eyes']['leftOpen'], 0.75)
        self.assertAlmostEqual(payload['eyes']['rightOpen'], 0.5)
        self.assertAlmostEqual(payload['mouth']['open'], 0.4)
        self.assertAlmostEqual(payload['mouth']['smile'], 0.7)
        self.assertAlmostEqual(payload['cheekPuff'], 0.3)
        self.assertNotIn('tongueOut', payload)

    def test_packaged_model_hash(self):
        path = os.path.join(os.path.dirname(__file__), 'models', 'face_landmarker.task')
        with open(path, 'rb') as model_file:
            digest = hashlib.sha256(model_file.read()).hexdigest()
        self.assertEqual(
            digest,
            '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff',
        )


class TestWebSocketPortConfig(unittest.TestCase):
    def test_signed_atomic_port_file(self):
        from ws_config import (
            load_port,
            save_port,
            sign_launcher_heartbeat,
            sign_shutdown_command,
            verify_launcher_heartbeat,
            verify_port_data,
            verify_shutdown_command,
        )

        tmp = tempfile.mkdtemp()
        old_user_dir = os.environ.get('MIKU_USER_DIR')
        os.environ['MIKU_USER_DIR'] = tmp
        try:
            save_port(18769, token='secret', launch_session='launch-1')
            data = load_port()
            self.assertTrue(verify_port_data(data, 'secret', max_age_ms=5_000))
            self.assertFalse(verify_port_data(data, 'wrong', max_age_ms=5_000))
            self.assertEqual(list(os.scandir(tmp))[0].name, 'ws_port.json')
            ts = int(time.time() * 1000)
            command = {
                'action': 'shutdown',
                'launch_session': 'launch-1',
                'ts': ts,
                'signature': sign_shutdown_command('secret', 'launch-1', ts),
            }
            self.assertTrue(verify_shutdown_command(command, 'secret', 'launch-1'))
            self.assertFalse(verify_shutdown_command(command, 'secret', 'other-launch'))

            heartbeat = {
                'action': 'heartbeat',
                'launch_session': 'launch-1',
                'ts': ts,
                'signature': sign_launcher_heartbeat('secret', 'launch-1', ts),
            }
            self.assertEqual(
                verify_launcher_heartbeat(
                    heartbeat, 'secret', 'launch-1', now_ms=ts
                ),
                ts,
            )
            self.assertIsNone(
                verify_launcher_heartbeat(
                    heartbeat, 'secret', 'other-launch', now_ms=ts
                )
            )
            self.assertIsNone(
                verify_launcher_heartbeat(
                    heartbeat, 'wrong', 'launch-1', now_ms=ts
                )
            )
            self.assertIsNone(
                verify_launcher_heartbeat(
                    heartbeat, 'secret', 'launch-1', now_ms=ts + 6_001
                )
            )
            self.assertIsNone(
                verify_launcher_heartbeat(
                    heartbeat, 'secret', 'launch-1', now_ms=ts - 1
                )
            )
        finally:
            if old_user_dir is None:
                os.environ.pop('MIKU_USER_DIR', None)
            else:
                os.environ['MIKU_USER_DIR'] = old_user_dir
            shutil.rmtree(tmp, ignore_errors=True)


class TestLLMSafety(unittest.TestCase):
    def test_base_url_validation(self):
        from llm import validate_llm_base_url

        self.assertEqual(validate_llm_base_url('https://api.deepseek.com/'), 'https://api.deepseek.com')
        self.assertEqual(validate_llm_base_url('http://127.0.0.1:8080/v1'), 'http://127.0.0.1:8080/v1')
        with self.assertRaisesRegex(ValueError, 'insecure_base_url'):
            validate_llm_base_url('http://example.com/v1')
        with self.assertRaisesRegex(ValueError, 'invalid_base_url'):
            validate_llm_base_url('file:///tmp/model')

    def test_chat_calls_are_serialized_and_history_is_paired(self):
        from llm import MikuLLM

        tmp = tempfile.mkdtemp()
        old_user_dir = os.environ.get('MIKU_USER_DIR')
        os.environ['MIKU_USER_DIR'] = tmp

        class Completions:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def create(self, **kwargs):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self.lock:
                    self.active -= 1
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='reply'))]
                )

        try:
            llm = MikuLLM()
            completions = Completions()
            llm.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
            llm.api_key = 'test'
            llm.model = 'test-model'
            threads = [
                threading.Thread(target=llm.chat_with_miku, args=(f'message-{index}',))
                for index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
            self.assertEqual(completions.max_active, 1)
            self.assertEqual([item['role'] for item in llm.chat_history], ['user', 'assistant', 'user', 'assistant'])
            llm.close()
        finally:
            if old_user_dir is None:
                os.environ.pop('MIKU_USER_DIR', None)
            else:
                os.environ['MIKU_USER_DIR'] = old_user_dir
            shutil.rmtree(tmp, ignore_errors=True)


class TestBackendProcessShutdown(unittest.TestCase):
    @staticmethod
    def _atomic_json(path, payload):
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def test_broken_launcher_log_pipe_does_not_break_lifecycle_output(self):
        import main as backend_main

        class BrokenStream:
            encoding = 'utf-8'

            def write(self, _value):
                raise BrokenPipeError()

            def flush(self):
                raise BrokenPipeError()

        wrapped = backend_main._BrokenPipeSafeTextIO(BrokenStream())
        self.assertEqual(wrapped.write('shutdown'), len('shutdown'))
        self.assertIsNone(wrapped.flush())

    def test_launcher_heartbeat_expiry_exits_real_process(self):
        from ws_config import sign_launcher_heartbeat, verify_port_data

        tmp = tempfile.mkdtemp()
        token = 'heartbeat-process-token-0123456789'
        session = 'heartbeat-process-session'
        env = os.environ.copy()
        env.pop('MIKU_EXPECT_LAUNCHER_HEARTBEAT', None)
        env.update({
            'MIKU_USER_DIR': tmp,
            'MIKU_RESOURCES': tmp,
            'MIKU_WS_TOKEN': token,
            'MIKU_LAUNCH_SESSION': session,
            'MIKU_EXPECT_LAUNCHER_HEARTBEAT': '1',
            'MIKU_CAMERA_MONITOR_ON_START': '0',
            'MIKU_FACE_DETECTOR': 'haar',
            'PYTHONUNBUFFERED': '1',
        })
        heartbeat_path = os.path.join(tmp, 'launcher_heartbeat.json')
        heartbeat_stop = threading.Event()

        def write_heartbeats():
            while not heartbeat_stop.is_set():
                now_ms = int(time.time() * 1000)
                self._atomic_json(heartbeat_path, {
                    'action': 'heartbeat',
                    'launch_session': session,
                    'ts': now_ms,
                    'signature': sign_launcher_heartbeat(token, session, now_ms),
                })
                heartbeat_stop.wait(0.5)

        heartbeat_thread = threading.Thread(target=write_heartbeats, daemon=True)
        heartbeat_thread.start()
        backend_dir = os.path.dirname(__file__)
        proc = subprocess.Popen(
            [sys.executable, 'main.py'],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        output = ''
        try:
            port_path = os.path.join(tmp, 'ws_port.json')
            deadline = time.time() + 45
            while not os.path.exists(port_path) and time.time() < deadline:
                if proc.poll() is not None:
                    output = proc.communicate(timeout=1)[0]
                    self.fail(f'backend exited before ready:\n{output}')
                time.sleep(0.05)
            self.assertTrue(os.path.exists(port_path), 'backend did not become ready')
            with open(port_path, 'r', encoding='utf-8') as f:
                self.assertTrue(
                    verify_port_data(json.load(f), token, max_age_ms=30_000)
                )

            time.sleep(1.2)
            self.assertIsNone(proc.poll(), output)
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)
            stopped_at = time.monotonic()
            proc.wait(timeout=10)
            elapsed = time.monotonic() - stopped_at
            output = proc.communicate(timeout=1)[0]
            self.assertEqual(proc.returncode, 0, output)
            self.assertLess(elapsed, 8.0, output)
            self.assertIn('Signed launcher heartbeat expired', output)
            self.assertIn('Backend Cleaned Up', output)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)
            if proc.stdout is not None:
                proc.stdout.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_signed_shutdown_exits_real_process_within_five_seconds(self):
        from ws_config import sign_shutdown_command, verify_port_data

        tmp = tempfile.mkdtemp()
        token = 'process-test-token-0123456789'
        session = 'process-test-session'
        env = os.environ.copy()
        env.update({
            'MIKU_USER_DIR': tmp,
            'MIKU_RESOURCES': tmp,
            'MIKU_WS_TOKEN': token,
            'MIKU_LAUNCH_SESSION': session,
            'MIKU_CAMERA_MONITOR_ON_START': '0',
            'MIKU_FACE_DETECTOR': 'haar',
            'PYTHONUNBUFFERED': '1',
        })
        backend_dir = os.path.dirname(__file__)
        proc = subprocess.Popen(
            [sys.executable, 'main.py'],
            cwd=backend_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        output = ''
        try:
            port_path = os.path.join(tmp, 'ws_port.json')
            deadline = time.time() + 20
            while not os.path.exists(port_path) and time.time() < deadline:
                if proc.poll() is not None:
                    output = proc.communicate(timeout=1)[0]
                    self.fail(f'backend exited before ready:\n{output}')
                time.sleep(0.05)
            self.assertTrue(os.path.exists(port_path), 'backend did not write ws_port.json')
            with open(port_path, 'r', encoding='utf-8') as f:
                port_data = json.load(f)
            self.assertTrue(verify_port_data(port_data, token, max_age_ms=30_000))

            async def verify_authenticated_protocol():
                import websockets

                uri = f"ws://{port_data['host']}:{port_data['port']}"
                async with websockets.connect(uri) as ws:
                    await ws.send(json.dumps({'type': 'authenticate', 'token': token}))
                    authenticated = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    self.assertEqual(authenticated, {'type': 'authenticated', 'ok': True})
                    await ws.send(json.dumps({'type': 'get_camera_status'}))
                    camera_status = None
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('type') == 'camera_status':
                            camera_status = message
                            break
                    self.assertIsNotNone(camera_status)
                    self.assertIs(camera_status['connected'], False)

                    await ws.send(json.dumps({'type': 'toggle_camera', 'state': 'false'}))
                    invalid_camera = None
                    for _ in range(3):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('error') == 'invalid_camera_state':
                            invalid_camera = message
                            break
                    self.assertIsNotNone(invalid_camera)
                    self.assertIs(invalid_camera['connected'], False)

                    await ws.send(json.dumps({
                        'type': 'set_emotion_recognition', 'enabled': False,
                    }))
                    emotion_status = None
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('type') == 'emotion_recognition_status':
                            emotion_status = message
                            break
                    self.assertIsNotNone(emotion_status)
                    self.assertIs(emotion_status['enabled'], False)

                    await ws.send(json.dumps({
                        'type': 'set_face_tracking', 'enabled': 'true',
                    }))
                    invalid_face = None
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('error') == 'invalid_face_tracking_state':
                            invalid_face = message
                            break
                    self.assertIsNotNone(invalid_face)
                    self.assertEqual(invalid_face.get('error'), 'invalid_face_tracking_state')

                    await ws.send(json.dumps({
                        'type': 'set_camera_suspended',
                        'reason': 'training_capture',
                        'suspended': True,
                    }))
                    suspended_status = None
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('type') == 'camera_status' and message.get('suspended') is True:
                            suspended_status = message
                            break
                    self.assertIsNotNone(suspended_status)

                    await ws.send(json.dumps({
                        'type': 'set_camera_suspended',
                        'reason': 'training_capture',
                        'suspended': False,
                    }))
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                        if message.get('type') == 'camera_status' and message.get('suspended') is False:
                            break

                    await ws.send(json.dumps({'type': 'pause_focus', 'paused': 'false'}))
                    invalid_pause = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    self.assertEqual(invalid_pause.get('error'), 'invalid_paused_state')

                    await ws.send(json.dumps({'type': 'end_focus', 'completed': 'yes'}))
                    invalid_completed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    self.assertEqual(invalid_completed.get('error'), 'invalid_completed_state')

            asyncio.run(verify_authenticated_protocol())

            ts = int(time.time() * 1000)
            command = {
                'action': 'shutdown',
                'launch_session': session,
                'ts': ts,
                'signature': sign_shutdown_command(token, session, ts),
            }
            control_tmp = os.path.join(tmp, 'backend_control.json.tmp')
            control_path = os.path.join(tmp, 'backend_control.json')
            with open(control_tmp, 'w', encoding='utf-8') as f:
                json.dump(command, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(control_tmp, control_path)

            started = time.monotonic()
            proc.wait(timeout=5)
            elapsed = time.monotonic() - started
            output = proc.communicate(timeout=1)[0]
            self.assertEqual(proc.returncode, 0, output)
            self.assertLess(elapsed, 5.0, output)
            self.assertIn('Authenticated shutdown command received', output)
            self.assertIn('Backend Cleaned Up', output)
            print(f"  real signed shutdown elapsed={elapsed:.3f}s")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
