"""
Compatibility shim — all architectures live in backend/models_def.py.
Train scripts should import from models_def; this file re-exports for legacy imports.
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), '..', 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, os.path.abspath(_BACKEND))

from models_def import EmotionCNN, GrayscaleMobileNetV2, RNNAttentionNetwork  # noqa: E402,F401

__all__ = ['EmotionCNN', 'GrayscaleMobileNetV2', 'RNNAttentionNetwork']
