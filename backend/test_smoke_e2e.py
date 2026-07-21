"""
End-to-end smoke (no camera UI required):
  1) Start WS server handlers in-process (lightweight)
  2) Exercise focus pause / emotion logging / short-session discard
  3) Verify MediaPipe Tasks face detector boots
  4) Optional: --live for real camera frames

Run:
  python test_smoke_e2e.py
  python test_smoke_e2e.py --live
"""
import argparse
import os
import sys
import time
import tempfile
import shutil
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))


def test_mediapipe_tasks():
    from detector import EmotionDetector, _create_mp_tasks_face_detector
    det = _create_mp_tasks_face_detector()
    assert det is not None, "MediaPipe Tasks FaceDetector failed to init (model download?)"
    # Synthetic image — may return no face, but must not crash
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (40, 40, 40)
    # Draw a pale ellipse approximating a face for Haar/MP luck
    import cv2
    cv2.ellipse(frame, (320, 240), (80, 100), 0, 0, 360, (200, 180, 170), -1)
    ed = EmotionDetector(model_type='mock', smooth_window=3)
    # Force inject tasks detector from factory if present
    if det is not None:
        ed.mp_tasks_face = det
    face, coords = ed.extract_face(frame)
    print(f"  face extract: face={'yes' if face is not None else 'no'} coords={coords}")
    em, conf, bb = ed.detect_emotion(frame)
    print(f"  detect: {em} conf={conf:.2f}")
    print("  OK mediapipe/tasks + detector pipeline")


def test_logger_pause_and_short():
    from logger import EmotionLogger
    tmp = tempfile.mkdtemp()
    try:
        lg = EmotionLogger(log_dir=tmp, flush_interval_sec=999)
        lg.start_session(5)
        path = lg.log_file
        assert os.path.exists(path)
        lg.log_emotion('happy', 0.9)
        stats, mins = lg.end_session(
            miku_comment='x', paused_seconds=12, min_save_seconds=9999
        )
        # Should discard because min_save_seconds huge vs actual duration
        assert not os.path.exists(path), "short session file should be removed"
        print("  OK short-session discard")

        lg2 = EmotionLogger(log_dir=tmp, flush_interval_sec=999)
        lg2.start_session(5)
        lg2.log_emotion('anger', 0.8)
        lg2.log_emotion('anger', 0.7)
        stats, mins = lg2.end_session(
            miku_comment='ok', paused_seconds=30, min_save_seconds=0
        )
        assert 'anger' in stats and stats['anger'] > 0
        # file should exist and mention Paused
        assert lg2.log_file and os.path.exists(lg2.log_file)
        with open(lg2.log_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Paused' in content or '30' in content
        print("  OK pause field in report")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ws_protocol():
    import asyncio
    import json
    import websockets
    from websocket_server import MikuWebSocketServer

    got = []
    srv = MikuWebSocketServer(host='127.0.0.1', port=18767)

    def on_msg(d):
        got.append(d)
        if d.get('type') == 'ping':
            srv.send_to_all({'type': 'pong', 'ts': time.time()})

    srv.start(on_msg)
    time.sleep(0.4)

    async def client():
        async with websockets.connect('ws://127.0.0.1:18767') as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            await ws.send(json.dumps({'type': 'ping'}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            return ready, pong

    ready, pong = asyncio.run(client())
    assert ready['type'] == 'backend_ready'
    assert pong['type'] == 'pong'
    srv.stop()
    time.sleep(0.15)
    print("  OK websocket ready/ping/pong")


def test_live_camera(seconds=3):
    from camera import Camera
    from detector import EmotionDetector

    cam = Camera(device_index=0, target_fps=2)
    if not cam.start():
        print("  SKIP live: camera not available")
        return
    det = EmotionDetector(model_type='mock', smooth_window=3)
    # Prefer real model if present
    cnn = os.path.join(os.path.dirname(__file__), 'models', 'best_cnn.pth')
    if os.path.exists(cnn):
        det.switch_model('cnn', force=True)

    t0 = time.time()
    samples = []
    while time.time() - t0 < seconds:
        frame = cam.get_frame()
        if frame is not None:
            em, conf, bb = det.detect_emotion(frame)
            samples.append((em, conf))
            print(f"  live: {em} {conf:.2f} shape={frame.shape}")
        time.sleep(0.4)
    cam.stop()
    assert samples, "no frames received from camera"
    print(f"  OK live camera ({len(samples)} samples)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Also test real camera')
    args = parser.parse_args()

    print("=== Miku Cure E2E Smoke ===")
    test_mediapipe_tasks()
    test_logger_pause_and_short()
    test_ws_protocol()
    if args.live:
        test_live_camera()
    print("=== ALL SMOKE CHECKS PASSED ===")


if __name__ == '__main__':
    main()
