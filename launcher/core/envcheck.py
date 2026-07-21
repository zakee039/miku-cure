"""启动环境检查（子进程强制隐藏控制台）。"""
from __future__ import annotations

from dataclasses import dataclass, field

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
from .winproc import run_hidden


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


def run_env_check(progress=None) -> EnvReport:
    """progress: optional callable(message: str, percent: int)."""
    def _p(msg: str, pct: int) -> None:
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
            r = run_hidden(
                [str(py), "-c", "import cv2,numpy,torch; print('OK', torch.__version__)"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(BACKEND_DIR),
            )
            dep_ok = r.returncode == 0 and "OK" in (r.stdout or "")
            dep_detail = (r.stdout or r.stderr or "").strip()[:200]
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
