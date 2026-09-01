import math
import os
import threading
import time

import numpy as np


class FaceTracker:
    """MediaPipe FaceLandmarker live-stream adapter with semantic output."""

    def __init__(self, model_path, result_callback=None):
        self.model_path = os.path.abspath(model_path)
        self.result_callback = result_callback
        self.landmarker = None
        self.last_error = None
        self._metadata = {}
        self._metadata_lock = threading.Lock()
        self._last_timestamp_ms = 0

    @property
    def is_ready(self):
        return self.landmarker is not None and self.last_error is None

    def start(self):
        if self.landmarker is not None and self.last_error is None:
            return True
        if self.landmarker is not None:
            self.close()
        if not os.path.isfile(self.model_path):
            self.last_error = 'face_landmarker_model_missing'
            return False
        try:
            import mediapipe as mp

            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=self.model_path),
                running_mode=mp.tasks.vision.RunningMode.LIVE_STREAM,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                result_callback=self._handle_result,
            )
            self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = 'face_landmarker_init_failed'
            print(f'FaceTracker: initialization failed: {exc}')
            self.landmarker = None
            return False

    def submit(self, snapshot, generation=0):
        if not self.is_ready or snapshot is None:
            return False
        try:
            import cv2
            import mediapipe as mp

            rgb = cv2.cvtColor(snapshot.image, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = max(
                self._last_timestamp_ms + 1,
                int(snapshot.captured_at * 1000),
            )
            self._last_timestamp_ms = timestamp_ms
            with self._metadata_lock:
                self._metadata[timestamp_ms] = (
                    snapshot.sequence, snapshot.captured_at, int(generation),
                )
                if len(self._metadata) > 128:
                    for key in sorted(self._metadata)[:-64]:
                        self._metadata.pop(key, None)
            self.landmarker.detect_async(image, timestamp_ms)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = 'face_landmarker_inference_failed'
            print(f'FaceTracker: inference failed: {exc}')
            return False

    def _handle_result(self, result, _output_image, timestamp_ms):
        with self._metadata_lock:
            sequence, captured_at, generation = self._metadata.pop(
                timestamp_ms, (0, time.monotonic(), 0)
            )
        try:
            payload = self._to_semantic_payload(result)
            payload.update({
                'type': 'face_tracking',
                'sequence': int(sequence),
                'capturedAt': float(captured_at),
                'generation': int(generation),
            })
            callback = self.result_callback
            if callback:
                callback(payload)
        except Exception as exc:
            self.last_error = 'face_landmarker_result_failed'
            print(f'FaceTracker: result conversion failed: {exc}')

    @staticmethod
    def _category_map(result):
        if not getattr(result, 'face_blendshapes', None):
            return {}
        return {
            item.category_name: float(item.score)
            for item in result.face_blendshapes[0]
            if isinstance(item.category_name, str)
        }

    @staticmethod
    def _head_pose(result):
        matrices = getattr(result, 'facial_transformation_matrixes', None)
        if not matrices:
            return 0.0, 0.0, 0.0
        matrix = np.asarray(matrices[0], dtype=np.float64).reshape(4, 4)
        rotation = matrix[:3, :3]
        sy = math.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2)
        if sy > 1e-6:
            pitch = math.atan2(rotation[2, 1], rotation[2, 2])
            yaw = math.atan2(-rotation[2, 0], sy)
            roll = math.atan2(rotation[1, 0], rotation[0, 0])
        else:
            pitch = math.atan2(-rotation[1, 2], rotation[1, 1])
            yaw = math.atan2(-rotation[2, 0], sy)
            roll = 0.0
        degrees = tuple(math.degrees(value) for value in (yaw, pitch, roll))
        return tuple(float(np.clip(value / 30.0, -1.0, 1.0)) for value in degrees)

    def _to_semantic_payload(self, result):
        if not getattr(result, 'face_landmarks', None):
            return {'valid': False, 'reason': 'face_lost'}
        blend = self._category_map(result)
        score = lambda name: float(np.clip(blend.get(name, 0.0), 0.0, 1.0))
        head_x, head_y, head_z = self._head_pose(result)
        eye_x = (
            score('eyeLookOutRight') + score('eyeLookInLeft')
            - score('eyeLookInRight') - score('eyeLookOutLeft')
        ) / 2.0
        eye_y = (
            score('eyeLookUpLeft') + score('eyeLookUpRight')
            - score('eyeLookDownLeft') - score('eyeLookDownRight')
        ) / 2.0
        smile = (
            score('mouthSmileLeft') + score('mouthSmileRight')
            - score('mouthFrownLeft') - score('mouthFrownRight')
        ) / 2.0
        mouth_x = (
            score('mouthRight') + score('jawRight')
            - score('mouthLeft') - score('jawLeft')
        ) / 2.0
        return {
            'valid': True,
            'head': {'x': head_x, 'y': head_y, 'z': head_z},
            'body': {'x': head_x * 0.33, 'y': head_y * 0.25, 'z': head_z * 0.33},
            'eyes': {
                'x': float(np.clip(eye_x, -1.0, 1.0)),
                'y': float(np.clip(eye_y, -1.0, 1.0)),
                'leftOpen': 1.0 - score('eyeBlinkLeft'),
                'rightOpen': 1.0 - score('eyeBlinkRight'),
            },
            'brows': {
                'leftY': float(np.clip(
                    score('browOuterUpLeft') + score('browInnerUp') - score('browDownLeft'),
                    -1.0, 1.0,
                )),
                'rightY': float(np.clip(
                    score('browOuterUpRight') + score('browInnerUp') - score('browDownRight'),
                    -1.0, 1.0,
                )),
                'form': float(np.clip(
                    score('browInnerUp') - (score('browDownLeft') + score('browDownRight')) / 2.0,
                    -1.0, 1.0,
                )),
            },
            'mouth': {
                'open': score('jawOpen'),
                'smile': float(np.clip(smile, -1.0, 1.0)),
                'pucker': max(score('mouthPucker'), score('mouthFunnel')),
                'x': float(np.clip(mouth_x, -1.0, 1.0)),
                'shrug': (score('mouthShrugLower') + score('mouthShrugUpper')) / 2.0,
                'rollLower': score('mouthRollLower'),
            },
            'cheekPuff': score('cheekPuff'),
        }

    def close(self):
        landmarker = self.landmarker
        self.landmarker = None
        with self._metadata_lock:
            self._metadata.clear()
        if landmarker is not None:
            try:
                landmarker.close()
            except Exception as exc:
                print(f'FaceTracker: close failed: {exc}')
