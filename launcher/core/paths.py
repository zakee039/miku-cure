"""项目路径解析与部署模式识别（dev / portable）。

对标 RAG-PRO launcher/core/paths.py：
- 源码开发：backend/.venv + frontend/node_modules
- 便携发行：runtime/python + PORTABLE_MANIFEST.json
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Miku Cure 启动器"
APP_VERSION = "1.2.1"


def _launcher_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


LAUNCHER_DIR = _launcher_dir()


def _meipass_dir() -> Path | None:
    """PyInstaller onefile unpack dir (contains bundled miku/icon.png if present)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return None


def _project_root() -> Path:
    env_root = os.environ.get("MIKU_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()

    candidate = LAUNCHER_DIR
    for _ in range(6):
        has_backend = (candidate / "backend" / "main.py").exists()
        has_frontend = (candidate / "frontend" / "main.js").exists()
        has_runtime = (candidate / "runtime" / "python" / "python.exe").exists()
        has_manifest = (candidate / "PORTABLE_MANIFEST.json").exists()
        if has_backend and (has_frontend or has_runtime or has_manifest):
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    return LAUNCHER_DIR.parent


PROJECT_ROOT = _project_root()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
MIKU_DIR = PROJECT_ROOT / "miku"
USER_DIR = PROJECT_ROOT / "user"
LOGS_DIR = PROJECT_ROOT / "logs"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
RUNTIME_PYTHON = PROJECT_ROOT / "runtime" / "python" / "python.exe"
PORTABLE_MANIFEST = PROJECT_ROOT / "PORTABLE_MANIFEST.json"
ELECTRON_EXE = FRONTEND_DIR / "node_modules" / "electron" / "dist" / "electron.exe"


def detect_deploy_mode() -> str:
    if PORTABLE_MANIFEST.exists():
        return "portable"
    if RUNTIME_PYTHON.exists():
        return "portable"
    if VENV_PYTHON.exists():
        return "dev"
    return "dev"


DEPLOY_MODE = detect_deploy_mode()
IS_PORTABLE = DEPLOY_MODE == "portable"


def deploy_mode_label() -> str:
    return "便携发行包" if IS_PORTABLE else "源码开发环境"


def deploy_mode_detail() -> str:
    if IS_PORTABLE:
        return f"runtime Python + 内置依赖\n根目录：{PROJECT_ROOT}"
    return f"backend/.venv + Electron\n根目录：{PROJECT_ROOT}"


def resolve_backend_python() -> Path:
    if IS_PORTABLE and RUNTIME_PYTHON.exists():
        return RUNTIME_PYTHON
    if VENV_PYTHON.exists():
        return VENV_PYTHON
    if RUNTIME_PYTHON.exists():
        return RUNTIME_PYTHON
    return Path("python")


def resolve_electron() -> Path | None:
    if ELECTRON_EXE.exists():
        return ELECTRON_EXE
    # portable layout may put electron under runtime/electron
    alt = PROJECT_ROOT / "runtime" / "electron" / "electron.exe"
    if alt.exists():
        return alt
    return None
