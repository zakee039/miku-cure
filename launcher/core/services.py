"""后端 Python + Electron 桌宠 的启动/停止与日志泵。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .paths import (
    BACKEND_DIR,
    FRONTEND_DIR,
    IS_PORTABLE,
    PROJECT_ROOT,
    USER_DIR,
    resolve_backend_python,
    resolve_electron,
)
from .winproc import popen_hidden, run_hidden

LogCallback = Callable[[str, str], None]
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _kill_tree(pid: int) -> None:
    """Kill process tree with taskkill only — never spawn PowerShell (AV/firewall)."""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            run_hidden(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                timeout=3,
            )
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def _pet_control_path() -> Path:
    return USER_DIR / "pet_control.json"


def write_pet_command(action: str, **extra) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"action": action, "ts": time.time(), **extra}
    _pet_control_path().write_text(json.dumps(payload), encoding="utf-8")


def read_pet_control() -> dict:
    p = _pet_control_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


@dataclass
class ServiceManager:
    log: LogCallback = field(default=lambda *_: None)
    backend_proc: subprocess.Popen | None = None
    electron_proc: subprocess.Popen | None = None
    pet_hidden: bool = False
    launch_session: str = ""
    _pumps: list[threading.Thread] = field(default_factory=list)
    _stop_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def backend_running(self) -> bool:
        return self.backend_proc is not None and self.backend_proc.poll() is None

    def electron_running(self) -> bool:
        return self.electron_proc is not None and self.electron_proc.poll() is None

    def any_running(self) -> bool:
        return self.backend_running() or self.electron_running()

    def _pump(self, source: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.log(source, strip_ansi(line.rstrip("\n")))
        except Exception as e:
            self.log(source, f"[log pump ended] {e}")

    def start_backend(self) -> bool:
        if self.backend_running():
            self.log("system", "后端已在运行")
            return True
        py = resolve_backend_python()
        main_py = BACKEND_DIR / "main.py"
        if not main_py.exists():
            self.log("system", f"找不到后端入口：{main_py}")
            return False
        if not Path(py).exists() and str(py) != "python":
            self.log("system", f"找不到 Python：{py}")
            return False

        USER_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["MIKU_USER_DIR"] = str(USER_DIR)
        env["MIKU_RESOURCES"] = str(PROJECT_ROOT)
        env["MIKU_PROJECT_ROOT"] = str(PROJECT_ROOT)
        try:
            config = json.loads((USER_DIR / "config.json").read_text(encoding="utf-8"))
        except Exception:
            config = {}
        monitor_on_start = config.get(
            "camera-monitor-on-start",
            config.get("launcher-auto-monitor", True),
        )
        env["MIKU_CAMERA_MONITOR_ON_START"] = "1" if monitor_on_start else "0"
        env.setdefault("CUDA_VISIBLE_DEVICES", "")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        self.log("system", f"启动后端（无窗口，子进程）：{py} main.py")
        try:
            # CREATE_NO_WINDOW keeps console hidden but process remains a child of launcher.
            # Do NOT use DETACHED / breakaway flags — parent tree must stay intact.
            self.backend_proc = popen_hidden(
                [str(py), "main.py"],
                cwd=str(BACKEND_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            self.log("system", f"后端启动失败：{e}")
            return False

        t = threading.Thread(
            target=self._pump, args=("backend", self.backend_proc), daemon=True
        )
        t.start()
        self._pumps.append(t)
        self.log("system", f"后端 PID={self.backend_proc.pid}（父进程=启动器）")
        return True

    def start_electron(self) -> bool:
        if self.electron_running():
            self.log("system", "桌宠窗口已在运行")
            return True
        electron = resolve_electron()
        if electron is None:
            self.log("system", "找不到 Electron 运行时")
            return False
        if not (FRONTEND_DIR / "main.js").exists():
            self.log("system", f"找不到前端入口：{FRONTEND_DIR / 'main.js'}")
            return False

        env = os.environ.copy()
        env["MIKU_USER_DIR"] = str(USER_DIR)
        env["MIKU_RESOURCES"] = str(PROJECT_ROOT)
        env["MIKU_PROJECT_ROOT"] = str(PROJECT_ROOT)
        env["MIKU_EXTERNAL_BACKEND"] = "1"
        if not self.launch_session:
            self.launch_session = uuid.uuid4().hex
        env["MIKU_LAUNCH_SESSION"] = self.launch_session
        env.setdefault("ELECTRON_NO_ATTACH_CONSOLE", "1")

        # Reset pet control state
        self.pet_hidden = False
        write_pet_command(
            "show",
            state="visible",
            launch_session=self.launch_session,
        )

        cmd = [str(electron), str(FRONTEND_DIR)]
        self.log("system", f"启动桌宠（无控制台，子进程）：{electron}")
        try:
            self.electron_proc = popen_hidden(
                cmd,
                cwd=str(FRONTEND_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            self.log("system", f"Electron 启动失败：{e}")
            return False

        t = threading.Thread(
            target=self._pump, args=("electron", self.electron_proc), daemon=True
        )
        t.start()
        self._pumps.append(t)
        self.log("system", f"Electron PID={self.electron_proc.pid}")
        return True

    def start_all(self, progress: Callable[[str, int], None] | None = None) -> bool:
        def _p(msg: str, pct: int) -> None:
            if progress:
                progress(msg, pct)
            self.log("system", msg)

        # Invalidate any pet_closed left by a previous Electron process before
        # the backend becomes visible to the launcher's status timer.
        self.launch_session = uuid.uuid4().hex
        write_pet_command(
            "starting",
            state="starting",
            launch_session=self.launch_session,
        )

        _p("正在启动后端服务…", 20)
        ok_b = self.start_backend()
        if not ok_b:
            _p("后端启动失败", 100)
            return False

        _p("等待后端就绪…", 45)
        for i in range(8):
            time.sleep(0.2)
            if progress:
                progress("等待后端就绪…", 45 + i * 3)

        _p("正在启动桌宠窗口…", 75)
        ok_e = self.start_electron()
        if ok_e:
            _p("启动完成", 100)
        else:
            _p("桌宠启动失败（后端仍在运行，可点停止服务）", 100)
        return ok_b and ok_e

    def hide_pet(self) -> None:
        if not self.electron_running():
            self.log("system", "桌宠未运行，无法隐藏")
            return
        self.pet_hidden = True
        write_pet_command(
            "hide", state="hidden", launch_session=self.launch_session
        )
        self.log("system", "已请求隐藏桌宠窗口")

    def show_pet(self) -> None:
        if not self.electron_running():
            self.log("system", "桌宠未运行，无法显示")
            return
        self.pet_hidden = False
        write_pet_command(
            "show", state="visible", launch_session=self.launch_session
        )
        self.log("system", "已请求显示桌宠窗口")

    def toggle_pet(self) -> None:
        if self.pet_hidden:
            self.show_pet()
        else:
            self.hide_pet()

    def stop_backend_only(self) -> None:
        """Stop Python backend using only tracked PIDs (no PowerShell)."""
        with self._stop_lock:
            killed_pids: set[int] = set()
            proc = self.backend_proc
            if proc and proc.poll() is None:
                pid = proc.pid
                _kill_tree(pid)
                if proc.poll() is None:
                    try:
                        proc.kill()
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                killed_pids.add(pid)
                self.log("system", f"已结束后端 PID={pid}")
            if self.backend_proc is proc:
                self.backend_proc = None

            pid_file = USER_DIR / "backend.pid"
            if pid_file.exists():
                try:
                    raw = pid_file.read_text(encoding="utf-8").strip()
                    if raw.isdigit() and int(raw) not in killed_pids:
                        _kill_tree(int(raw))
                    pid_file.unlink(missing_ok=True)
                except Exception:
                    pass

    def stop_all(self) -> None:
        with self._stop_lock:
            self.log("system", "正在停止服务…")
            # Ask electron to quit gracefully first
            try:
                write_pet_command("quit", launch_session=self.launch_session)
                time.sleep(0.3)
            except Exception:
                pass

            proc = self.electron_proc
            if proc and proc.poll() is None:
                pid = proc.pid
                _kill_tree(pid)
                if proc.poll() is None:
                    try:
                        proc.kill()
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                self.log("system", f"已结束 Electron PID={pid}")
            if self.electron_proc is proc:
                self.electron_proc = None
            self.pet_hidden = False

            self.stop_backend_only()
            self.log("system", "服务已停止")

    def status_text(self) -> str:
        b = "运行中" if self.backend_running() else "已停止"
        if self.electron_running():
            e = "已隐藏" if self.pet_hidden else "运行中"
        else:
            e = "已停止"
        mode = "便携" if IS_PORTABLE else "开发"
        return f"[{mode}] 后端：{b}  ·  桌宠：{e}"
