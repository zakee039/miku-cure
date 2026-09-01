"""启动环境检查（子进程强制隐藏控制台）。"""
from __future__ import annotations

import subprocess
import time
import hashlib
from dataclasses import dataclass, field
from typing import Callable

from .paths import (
    BACKEND_DIR,
    ELECTRON_EXE,
    FRONTEND_DIR,
    IS_PORTABLE,
    MIKU_DIR,
    PROJECT_ROOT,
    RUNTIME_PYTHON,
    USER_DIR,
    VENV_PYTHON,
    resolve_backend_python,
)
from .winproc import popen_hidden


class EnvCheckCancelled(RuntimeError):
    """Raised internally when a launcher worker is asked to stop."""


def _dependency_probe(
    python: str,
    *,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 60.0,
) -> tuple[int, str, str]:
    """Run the import probe while remaining responsive to QThread shutdown."""
    proc = popen_hidden(
        [python, "-c", "import cv2,numpy,torch; print('OK', torch.__version__)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(BACKEND_DIR),
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.1)
            return proc.returncode, stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            should_cancel = cancelled is not None and cancelled()
            timed_out = time.monotonic() >= deadline
            if not should_cancel and not timed_out:
                continue

            try:
                proc.terminate()
                proc.communicate(timeout=1.0)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                    proc.communicate(timeout=1.0)
                except (OSError, subprocess.SubprocessError):
                    pass
            if should_cancel:
                raise EnvCheckCancelled("environment check cancelled")
            raise subprocess.TimeoutExpired(proc.args, timeout)


@dataclass
class CheckItem:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass
class EnvReport:
    items: list[CheckItem] = field(default_factory=list)

    @property
    def all_required_ok(self) -> bool:
        return all(i.ok for i in self.items if i.required)

    def summary_line(self) -> str:
        ok_n = sum(1 for i in self.items if i.ok)
        return f"环境检查 {ok_n}/{len(self.items)} 通过 · {'就绪' if self.all_required_ok else '存在问题'}"


def run_env_check(
    progress=None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> EnvReport:
    """progress: optional callable(message: str, percent: int)."""
    def _p(msg: str, pct: int) -> None:
        if cancelled is not None and cancelled():
            raise EnvCheckCancelled("environment check cancelled")
        if progress:
            progress(msg, pct)

    items: list[CheckItem] = []
    _p("环境检查中：项目路径…", 10)

    items.append(CheckItem(
        "项目根目录",
        (PROJECT_ROOT / "backend" / "main.py").exists(),
        str(PROJECT_ROOT),
    ))

    _p("环境检查中：Python 运行时…", 25)
    py = resolve_backend_python()
    py_ok = py.exists() if py.name.endswith(".exe") or py.suffix else True
    items.append(CheckItem(
        "Python 运行时",
        py_ok,
        str(py) if py_ok else f"未找到：期望 {RUNTIME_PYTHON if IS_PORTABLE else VENV_PYTHON}",
    ))

    # 核心依赖 import 探测（隐藏控制台，避免闪黑窗）
    dep_ok = False
    dep_detail = ""
    _p("环境检查中：加载依赖（torch / opencv）…", 45)
    if py_ok and str(py):
        try:
            returncode, stdout, stderr = _dependency_probe(
                str(py), cancelled=cancelled
            )
            dep_ok = returncode == 0 and "OK" in stdout
            dep_detail = (stdout or stderr).strip()[:200]
        except EnvCheckCancelled:
            raise
        except Exception as e:
            dep_detail = str(e)
    items.append(CheckItem("核心依赖 (cv2/numpy/torch)", dep_ok, dep_detail or "未检测"))

    _p("环境检查中：模型与前端…", 70)
    items.append(CheckItem(
        "后端入口 main.py",
        (BACKEND_DIR / "main.py").exists(),
        str(BACKEND_DIR / "main.py"),
    ))

    models = BACKEND_DIR / "models"
    pth = list(models.glob("*.pth")) if models.exists() else []
    items.append(CheckItem(
        "情绪模型权重",
        len(pth) > 0,
        f"{len(pth)} 个 .pth" if pth else f"缺少 {models}",
        required=False,
    ))

    face_landmarker = models / "face_landmarker.task"
    expected_face_hash = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
    face_hash = ""
    if face_landmarker.is_file():
        try:
            face_hash = hashlib.sha256(face_landmarker.read_bytes()).hexdigest()
        except OSError:
            face_hash = ""
    items.append(CheckItem(
        "面捕模型资产",
        face_hash == expected_face_hash,
        str(face_landmarker) if face_hash == expected_face_hash else "缺失或摘要不匹配（鼠标追踪仍可用）",
        required=False,
    ))

    items.append(CheckItem(
        "Electron 前端",
        (FRONTEND_DIR / "main.js").exists(),
        str(FRONTEND_DIR / "main.js"),
    ))

    elec = ELECTRON_EXE if ELECTRON_EXE.exists() else None
    items.append(CheckItem(
        "Electron 运行时",
        elec is not None,
        str(elec) if elec else f"缺少 {ELECTRON_EXE}",
    ))

    _p("环境检查中：媒体与用户目录…", 90)
    gif = MIKU_DIR / "gif"
    items.append(CheckItem(
        "媒体资源 miku/",
        MIKU_DIR.exists(),
        f"gif={gif.exists()}" if MIKU_DIR.exists() else "可选，缺失时仅无动画",
        required=False,
    ))

    USER_DIR.mkdir(parents=True, exist_ok=True)
    items.append(CheckItem("用户目录 user/", USER_DIR.exists(), str(USER_DIR)))

    _p("环境检查完成", 100)
    return EnvReport(items=items)
