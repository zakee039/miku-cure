"""Lifecycle management for the backend and Electron child processes."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .i18n import get_texts
from .jsonio import atomic_write_json, read_json
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
_CONTROL_MAX_AGE_SEC = 30.0
_HEARTBEAT_INTERVAL_SEC = 1.0


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _control_signature(token: str, action: str, launch_session: str, ts: int) -> str:
    payload = f"{action}:{launch_session}:{int(ts)}".encode("utf-8")
    return hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _signed_control_payload(
    action: str, launch_session: str, token: str, **extra
) -> dict:
    if not action or not launch_session or not token:
        raise ValueError("signed control commands require action, session, and token")
    ts = int(time.time() * 1000)
    return {
        "action": action,
        "launch_session": launch_session,
        "ts": ts,
        "signature": _control_signature(token, action, launch_session, ts),
        **extra,
    }


def validate_control_payload(
    payload: dict,
    launch_session: str,
    token: str,
    *,
    max_age_sec: float = _CONTROL_MAX_AGE_SEC,
) -> bool:
    if not isinstance(payload, dict) or not launch_session or not token:
        return False
    try:
        action = str(payload["action"])
        supplied_session = str(payload["launch_session"])
        ts = int(payload["ts"])
        signature = str(payload["signature"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        supplied_session != launch_session
        or abs(int(time.time() * 1000) - ts) > max_age_sec * 1000
    ):
        return False
    expected = _control_signature(token, action, launch_session, ts)
    return hmac.compare_digest(signature, expected)


def _pet_control_path() -> Path:
    return USER_DIR / "pet_control.json"


def _backend_control_path() -> Path:
    return USER_DIR / "backend_control.json"


def _launcher_heartbeat_path() -> Path:
    return USER_DIR / "launcher_heartbeat.json"


def write_pet_command(
    action: str,
    *,
    launch_session: str = "",
    token: str = "",
    **extra,
) -> None:
    payload = _signed_control_payload(action, launch_session, token, **extra)
    atomic_write_json(_pet_control_path(), payload)


def read_pet_control() -> dict:
    payload = read_json(_pet_control_path(), {})
    return payload if isinstance(payload, dict) else {}


def _force_kill_tree(pid: int) -> bool:
    """Force-kill a process tree only after its tracked Popen has timed out."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = run_hidden(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return result.returncode == 0
        os.kill(pid, 9)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _wait_for_exit(proc: subprocess.Popen, timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False
    except (OSError, ValueError):
        return proc.poll() is not None


@dataclass
class ServiceManager:
    log: LogCallback = field(default=lambda *_: None)
    backend_proc: subprocess.Popen | None = None
    electron_proc: subprocess.Popen | None = None
    pet_hidden: bool = False
    launch_session: str = ""
    ws_token: str = field(default="", repr=False)
    launch_display_point: tuple[int, int] | None = field(default=None, repr=False)
    _pumps: list[threading.Thread] = field(default_factory=list, repr=False)
    _lifecycle_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _startup_cancel: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _start_in_progress: bool = field(default=False, init=False, repr=False)
    _startup_done: threading.Event | None = field(default=None, init=False, repr=False)
    _heartbeat_stop: threading.Event | None = field(default=None, init=False, repr=False)
    _heartbeat_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _heartbeat_session: str = field(default="", init=False, repr=False)

    def backend_running(self) -> bool:
        return self.backend_proc is not None and self.backend_proc.poll() is None

    def electron_running(self) -> bool:
        return self.electron_proc is not None and self.electron_proc.poll() is None

    def any_running(self) -> bool:
        return self.backend_running() or self.electron_running()

    def accepts_pet_control(self, payload: dict) -> bool:
        return validate_control_payload(payload, self.launch_session, self.ws_token)

    def set_launch_display_point(self, x: int, y: int) -> None:
        self.launch_display_point = (int(x), int(y))

    def _new_launch_identity(self) -> None:
        self.launch_session = uuid.uuid4().hex
        self.ws_token = secrets.token_urlsafe(32)

    def _child_env(self) -> dict[str, str]:
        if not self.launch_session or not self.ws_token:
            self._new_launch_identity()
        env = os.environ.copy()
        env["MIKU_USER_DIR"] = str(USER_DIR)
        env["MIKU_RESOURCES"] = str(PROJECT_ROOT)
        env["MIKU_PROJECT_ROOT"] = str(PROJECT_ROOT)
        env["MIKU_LAUNCH_SESSION"] = self.launch_session
        env["MIKU_WS_TOKEN"] = self.ws_token
        return env

    @staticmethod
    def _heartbeat_payload(launch_session: str, token: str) -> dict:
        return _signed_control_payload("heartbeat", launch_session, token)

    def _heartbeat_loop(
        self,
        launch_session: str,
        token: str,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(_HEARTBEAT_INTERVAL_SEC):
            try:
                atomic_write_json(
                    _launcher_heartbeat_path(),
                    self._heartbeat_payload(launch_session, token),
                )
            except OSError:
                # A transient write error must not terminate process lifecycle
                # management; the next interval retries automatically.
                continue

    def _start_heartbeat_locked(self) -> None:
        thread = self._heartbeat_thread
        if (
            thread is not None
            and thread.is_alive()
            and self._heartbeat_session == self.launch_session
        ):
            return
        if thread is not None and thread.is_alive():
            self._stop_heartbeat_locked()
        stop_event = threading.Event()
        launch_session = self.launch_session
        token = self.ws_token
        try:
            atomic_write_json(
                _launcher_heartbeat_path(),
                self._heartbeat_payload(launch_session, token),
            )
        except OSError:
            pass
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(launch_session, token, stop_event),
            name="launcher-heartbeat",
            daemon=True,
        )
        self._heartbeat_stop = stop_event
        self._heartbeat_thread = thread
        self._heartbeat_session = launch_session
        thread.start()

    def _stop_heartbeat_locked(self) -> None:
        stop_event = self._heartbeat_stop
        thread = self._heartbeat_thread
        session = self._heartbeat_session or self.launch_session
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._heartbeat_stop = None
        self._heartbeat_thread = None
        self._heartbeat_session = ""

        path = _launcher_heartbeat_path()
        payload = read_json(path, {})
        try:
            if isinstance(payload, dict) and payload.get("launch_session") == session:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def _pump(self, source: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.log(source, strip_ansi(line.rstrip("\n")))
        except (OSError, UnicodeError, ValueError) as exc:
            self.log(source, f"[日志读取结束] {exc}")

    def _start_backend_locked(self) -> bool:
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

        env = self._child_env()
        env["PYTHONUNBUFFERED"] = "1"
        # Some environments invoke a Python shim which starts the real backend
        # as a grandchild. A signed heartbeat is the ownership/liveness proof.
        env["MIKU_EXPECT_LAUNCHER_HEARTBEAT"] = "1"
        config = read_json(USER_DIR / "config.json", {})
        if not isinstance(config, dict):
            config = {}
        monitor_on_start = config.get(
            "camera-monitor-on-start", config.get("launcher-auto-monitor", True)
        )
        env["MIKU_CAMERA_MONITOR_ON_START"] = "1" if monitor_on_start else "0"
        env.setdefault("CUDA_VISIBLE_DEVICES", "")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        self.log("system", f"启动后端（无窗口，子进程）：{py} main.py")
        try:
            proc = popen_hidden(
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
        except (OSError, subprocess.SubprocessError) as exc:
            self.log("system", f"后端启动失败：{exc}")
            return False

        self.backend_proc = proc
        self._start_heartbeat_locked()
        pump = threading.Thread(target=self._pump, args=("backend", proc), daemon=True)
        pump.start()
        self._pumps.append(pump)
        self.log("system", f"后端 PID={proc.pid}（父进程=启动器）")
        return True

    def start_backend(self) -> bool:
        with self._lifecycle_lock:
            return self._start_backend_locked()

    def _start_electron_locked(self) -> bool:
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

        env = self._child_env()
        env["MIKU_EXTERNAL_BACKEND"] = "1"
        env["MIKU_EXPECT_LAUNCHER_HEARTBEAT"] = "0"
        if self.launch_display_point is not None:
            env["MIKU_LAUNCH_DISPLAY_X"] = str(self.launch_display_point[0])
            env["MIKU_LAUNCH_DISPLAY_Y"] = str(self.launch_display_point[1])
        env.setdefault("ELECTRON_NO_ATTACH_CONSOLE", "1")

        self.pet_hidden = False
        write_pet_command(
            "show",
            state="visible",
            launch_session=self.launch_session,
            token=self.ws_token,
        )

        self.log("system", f"启动桌宠（无控制台，子进程）：{electron}")
        try:
            proc = popen_hidden(
                [str(electron), str(FRONTEND_DIR)],
                cwd=str(FRONTEND_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.log("system", f"Electron 启动失败：{exc}")
            return False

        self.electron_proc = proc
        self._start_heartbeat_locked()
        pump = threading.Thread(target=self._pump, args=("electron", proc), daemon=True)
        pump.start()
        self._pumps.append(pump)
        self.log("system", f"Electron PID={proc.pid}")
        return True

    def start_electron(self) -> bool:
        with self._lifecycle_lock:
            return self._start_electron_locked()

    def _valid_backend_port_file(self) -> bool:
        data = read_json(USER_DIR / "ws_port.json", {})
        if not isinstance(data, dict):
            return False
        try:
            host = str(data["host"])
            port = int(data["port"])
            ts = int(data["ts"])
            session = str(data["launch_session"])
            signature = str(data["signature"])
        except (KeyError, TypeError, ValueError):
            return False
        if host != "127.0.0.1" or not (1 <= port <= 65535):
            return False
        if session != self.launch_session or abs(int(time.time() * 1000) - ts) > 60_000:
            return False
        canonical = f"{host}:{port}:{ts}:{session}".encode("utf-8")
        expected = hmac.new(
            self.ws_token.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def _wait_backend_ready(
        self,
        timeout: float = 20.0,
        *,
        cancel_event: threading.Event | None = None,
        expected_proc: subprocess.Popen | None = None,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return False
            proc = expected_proc if expected_proc is not None else self.backend_proc
            if proc is None or proc.poll() is not None:
                return False
            if self._valid_backend_port_file():
                return True
            remaining = max(0.0, deadline - time.monotonic())
            delay = min(0.1, remaining)
            if cancel_event is not None:
                if cancel_event.wait(delay):
                    return False
            else:
                time.sleep(delay)
        return False

    def _wait_pet_ready(
        self,
        timeout: float = 15.0,
        *,
        cancel_event: threading.Event | None = None,
        expected_proc: subprocess.Popen | None = None,
    ) -> bool:
        """Require a signed renderer/media-ready proof, not merely an Electron PID."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return False
            proc = expected_proc if expected_proc is not None else self.electron_proc
            if proc is None or proc.poll() is not None:
                return False
            payload = read_pet_control()
            if (
                self.accepts_pet_control(payload)
                and payload.get("action") == "renderer_ready"
                and payload.get("state") == "visible"
                and isinstance(payload.get("media_count"), int)
                and payload["media_count"] > 0
            ):
                return True
            remaining = max(0.0, deadline - time.monotonic())
            delay = min(0.1, remaining)
            if cancel_event is not None:
                if cancel_event.wait(delay):
                    return False
            else:
                time.sleep(delay)
        return False

    def _stop_electron_process(self, proc: subprocess.Popen, grace_timeout: float = 2.0) -> None:
        if proc.poll() is not None:
            return
        try:
            write_pet_command(
                "quit",
                launch_session=self.launch_session,
                token=self.ws_token,
            )
        except OSError:
            pass
        if not _wait_for_exit(proc, grace_timeout):
            self._force_tracked_process(proc, " Electron")

    def cancel_startup(self) -> None:
        """Wake a backend-readiness wait without waiting for its timeout."""
        self._startup_cancel.set()

    def stop_heartbeat(self) -> None:
        """Stop the external-child watchdog when the launcher event loop exits."""
        with self._lifecycle_lock:
            self._stop_heartbeat_locked()

    def start_all(self, progress: Callable[[str, int], None] | None = None) -> bool:
        def report(message: str, percent: int) -> None:
            if progress:
                progress(message, percent)
            self.log("system", message)

        owns_start = False
        startup_done: threading.Event | None = None
        backend_proc: subprocess.Popen | None = None
        electron_proc: subprocess.Popen | None = None
        try:
            # Only process creation and handle publication are serialized. The
            # readiness wait deliberately happens outside this lock so Stop can
            # cancel it immediately.
            with self._lifecycle_lock:
                if self._start_in_progress:
                    self.log("system", "启动流程已在进行，忽略重复启动请求")
                    return False
                if self.any_running():
                    self.log("system", "服务正在运行，忽略重复启动请求")
                    return self.backend_running() and self.electron_running()

                self._start_in_progress = True
                owns_start = True
                startup_done = threading.Event()
                self._startup_done = startup_done
                self._startup_cancel.clear()
                self.backend_proc = None
                self.electron_proc = None
                self._new_launch_identity()
                write_pet_command(
                    "starting",
                    state="starting",
                    launch_session=self.launch_session,
                    token=self.ws_token,
                )

                report("正在启动后端服务…", 20)
                if not self._start_backend_locked():
                    report("后端启动失败", 100)
                    return False
                backend_proc = self.backend_proc

            report("等待后端就绪…", 45)
            ready = self._wait_backend_ready(
                cancel_event=self._startup_cancel,
                expected_proc=backend_proc,
            )

            reclaim_backend: subprocess.Popen | None = None
            startup_cancelled = False
            with self._lifecycle_lock:
                if self._startup_cancel.is_set():
                    startup_cancelled = True
                    if self.backend_proc is backend_proc:
                        self.backend_proc = None
                        reclaim_backend = backend_proc
                    report("启动已取消", 100)
                elif not ready or self.backend_proc is not backend_proc:
                    if self.backend_proc is backend_proc:
                        # Transfer ownership away from shared state before the
                        # potentially blocking cleanup below.
                        self.backend_proc = None
                        reclaim_backend = backend_proc
                    report("后端未能就绪，正在回收启动进程…", 80)
                else:
                    report("正在启动桌宠窗口…", 75)
                    if self._start_electron_locked():
                        electron_proc = self.electron_proc

                    elif self.backend_proc is backend_proc:
                        self.backend_proc = None
                        reclaim_backend = backend_proc

            reclaim_electron: subprocess.Popen | None = None
            if electron_proc is not None:
                report("等待桌宠界面就绪…", 88)
                pet_ready = self._wait_pet_ready(
                    cancel_event=self._startup_cancel,
                    expected_proc=electron_proc,
                )
                with self._lifecycle_lock:
                    if (
                        pet_ready
                        and not self._startup_cancel.is_set()
                        and self.electron_proc is electron_proc
                        and self.backend_proc is backend_proc
                    ):
                        report("启动完成", 100)
                        return True
                    startup_cancelled = self._startup_cancel.is_set()
                    if self.electron_proc is electron_proc:
                        self.electron_proc = None
                        reclaim_electron = electron_proc
                    if self.backend_proc is backend_proc:
                        self.backend_proc = None
                        reclaim_backend = backend_proc
                    report(
                        "启动已取消" if startup_cancelled else "桌宠界面未能就绪，正在回收服务…",
                        90,
                    )

            if reclaim_electron is not None:
                self._stop_electron_process(reclaim_electron)

            if reclaim_backend is not None:
                self._stop_backend_process(reclaim_backend, grace_timeout=2.0)
                with self._lifecycle_lock:
                    if not self.any_running():
                        self._stop_heartbeat_locked()
            if startup_cancelled:
                return False
            report(
                "桌宠启动失败，后端已回收" if ready else "后端启动失败",
                100,
            )
            return False
        finally:
            if owns_start:
                with self._lifecycle_lock:
                    self._start_in_progress = False
                if startup_done is not None:
                    startup_done.set()

    def hide_pet(self) -> None:
        with self._lifecycle_lock:
            if not self.electron_running():
                self.log("system", "桌宠未运行，无法隐藏")
                return
            self.pet_hidden = True
            write_pet_command(
                "hide",
                state="hidden",
                launch_session=self.launch_session,
                token=self.ws_token,
            )
            self.log("system", "已请求隐藏桌宠窗口")

    def show_pet(self) -> None:
        with self._lifecycle_lock:
            if not self.electron_running():
                self.log("system", "桌宠未运行，无法显示")
                return
            self.pet_hidden = False
            write_pet_command(
                "show",
                state="visible",
                launch_session=self.launch_session,
                token=self.ws_token,
            )
            self.log("system", "已请求显示桌宠窗口")

    def toggle_pet(self) -> None:
        if self.pet_hidden:
            self.show_pet()
        else:
            self.hide_pet()

    def set_language(self, language: str) -> bool:
        if language not in {"zh", "ja", "en"}:
            self.log("system", f"忽略无效语言设置：{language}")
            return False
        with self._lifecycle_lock:
            if not self.electron_running():
                return False
            write_pet_command(
                "language",
                lang=language,
                launch_session=self.launch_session,
                token=self.ws_token,
            )
            return True

    def _write_backend_shutdown(self) -> None:
        payload = _signed_control_payload(
            "shutdown", self.launch_session, self.ws_token
        )
        atomic_write_json(_backend_control_path(), payload)

    def _force_tracked_process(self, proc: subprocess.Popen, label: str) -> None:
        pid = proc.pid
        killed = False
        if os.name == "nt":
            # taskkill /T is used only for the Popen tracked by this launch.
            killed = _force_kill_tree(pid)
        else:
            try:
                proc.terminate()
            except (OSError, ProcessLookupError):
                pass
        exited = _wait_for_exit(proc, 2.0)
        if not exited:
            try:
                proc.kill()
            except (OSError, ProcessLookupError):
                pass
            exited = _wait_for_exit(proc, 2.0)
        if not killed and not exited:
            self.log("system", f"无法确认{label}已结束 PID={pid}")
            return
        self.log("system", f"已强制结束{label} PID={pid}")

    def _cleanup_pid_file(self, tracked_pid: int | None) -> None:
        path = USER_DIR / "backend.pid"
        if tracked_pid is None:
            return
        try:
            if path.read_text(encoding="utf-8").strip() == str(tracked_pid):
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def _stop_backend_process(
        self,
        proc: subprocess.Popen,
        *,
        request_sent: bool = False,
        grace_timeout: float = 8.0,
    ) -> None:
        pid = proc.pid
        if proc.poll() is None:
            if not request_sent:
                try:
                    self._write_backend_shutdown()
                    self.log("system", "已请求后端安全退出…")
                except OSError as exc:
                    self.log("system", f"无法写入后端退出请求：{exc}")
            if _wait_for_exit(proc, max(0.0, grace_timeout)):
                self.log("system", f"后端已正常停止 PID={pid}")
            else:
                self.log("system", f"后端退出超时，准备强制结束 PID={pid}")
                self._force_tracked_process(proc, "后端")
        self._cleanup_pid_file(pid)

    def _stop_backend_locked(
        self, *, request_sent: bool = False, grace_timeout: float = 8.0
    ) -> None:
        proc = self.backend_proc
        if proc is None:
            return
        self._stop_backend_process(
            proc,
            request_sent=request_sent,
            grace_timeout=grace_timeout,
        )
        if self.backend_proc is proc:
            self.backend_proc = None

    def stop_backend_only(self) -> None:
        """Stop only the backend process started and tracked by this launcher."""
        self._startup_cancel.set()
        startup_done: threading.Event | None = None
        with self._lifecycle_lock:
            self._startup_cancel.set()
            if self._start_in_progress:
                startup_done = self._startup_done
            grace_timeout = 2.0 if self._start_in_progress else 8.0
            self._stop_backend_locked(grace_timeout=grace_timeout)
            if not self.any_running():
                self._stop_heartbeat_locked()
        if startup_done is not None:
            startup_done.wait(timeout=8.0)

    def stop_all(self) -> None:
        # Setting the event needs no lifecycle lock and wakes start_all's
        # readiness wait immediately.
        self._startup_cancel.set()
        startup_done: threading.Event | None = None
        with self._lifecycle_lock:
            # start_all may have acquired the lock after the first set() and
            # cleared the event for a new launch. Reassert cancellation once
            # Stop owns the lifecycle lock.
            self._startup_cancel.set()
            self.log("system", "正在停止服务…")
            cancelling_start = self._start_in_progress
            if cancelling_start:
                startup_done = self._startup_done
                self.log("system", "已取消正在进行的启动流程")
            backend_request_sent = False
            backend_grace = 2.0 if cancelling_start else 8.0
            backend_deadline = time.monotonic() + backend_grace
            if self.backend_running():
                try:
                    self._write_backend_shutdown()
                    backend_request_sent = True
                    self.log("system", "已请求后端安全退出…")
                except OSError as exc:
                    self.log("system", f"无法写入后端退出请求：{exc}")

            proc = self.electron_proc
            if proc is not None:
                pid = proc.pid
                if proc.poll() is None:
                    try:
                        write_pet_command(
                            "quit",
                            launch_session=self.launch_session,
                            token=self.ws_token,
                        )
                    except OSError as exc:
                        self.log("system", f"无法写入桌宠退出请求：{exc}")
                    if _wait_for_exit(proc, 3.0):
                        self.log("system", f"Electron 已正常停止 PID={pid}")
                    else:
                        self.log("system", f"Electron 退出超时，准备强制结束 PID={pid}")
                        self._force_tracked_process(proc, " Electron")
                if self.electron_proc is proc:
                    self.electron_proc = None
            self.pet_hidden = False

            self._stop_backend_locked(
                request_sent=backend_request_sent,
                grace_timeout=max(0.0, backend_deadline - time.monotonic()),
            )
            self._stop_heartbeat_locked()
        if startup_done is not None:
            startup_done.wait(timeout=8.0)
        self.log("system", "服务已停止")

    def status_text(self, language: str = "zh") -> str:
        texts = get_texts(language)
        backend = texts["running"] if self.backend_running() else texts["stopped_state"]
        if self.electron_running():
            electron = texts["hidden"] if self.pet_hidden else texts["running"]
        else:
            electron = texts["stopped_state"]
        mode = texts["mode_short_portable"] if IS_PORTABLE else texts["mode_short_dev"]
        return texts["service_status"].format(
            mode=mode,
            backend=backend,
            pet=electron,
        )
