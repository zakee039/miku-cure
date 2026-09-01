from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from core import services  # noqa: E402
from core.jsonio import atomic_write_json, read_json  # noqa: E402


class FakeProcess:
    def __init__(self, pid: int, *, exits_on_wait: bool = False) -> None:
        self.pid = pid
        self.stdout = []
        self.returncode = None
        self.exits_on_wait = exits_on_wait
        self.terminate_called = False
        self.kill_called = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is not None:
            return self.returncode
        if self.exits_on_wait:
            self.returncode = 0
            return 0
        raise subprocess.TimeoutExpired(str(self.pid), timeout)

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True


class AtomicJsonTests(unittest.TestCase):
    def test_atomic_json_round_trip_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_write_json(path, {"value": "初音"}, indent=2)
            self.assertEqual(read_json(path), {"value": "初音"})
            self.assertEqual(list(Path(tmp).glob(".state.json.*.tmp")), [])


class ControlProtocolTests(unittest.TestCase):
    def test_unsigned_control_command_is_refused(self):
        with self.assertRaises(ValueError):
            services.write_pet_command("language", lang="ja")

    def test_signed_control_uses_milliseconds_and_validates(self):
        now = 1_800_000_000.125
        with mock.patch.object(services.time, "time", return_value=now):
            payload = services._signed_control_payload("quit", "session", "token")
            self.assertEqual(payload["ts"], 1_800_000_000_125)
            self.assertTrue(
                services.validate_control_payload(payload, "session", "token")
            )
            self.assertFalse(
                services.validate_control_payload(payload, "other", "token")
            )

    def test_stale_control_is_rejected(self):
        payload = services._signed_control_payload("quit", "session", "token")
        payload["ts"] -= 31_000
        payload["signature"] = services._control_signature(
            "token", "quit", "session", payload["ts"]
        )
        self.assertFalse(
            services.validate_control_payload(payload, "session", "token")
        )

    def test_ws_port_contract_matches_backend_canonical_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = services.ServiceManager()
            manager.launch_session = "launch"
            manager.ws_token = "secret"
            now_ms = int(time.time() * 1000)
            canonical = f"127.0.0.1:13939:{now_ms}:launch"
            signature = hmac.new(
                b"secret", canonical.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            atomic_write_json(
                Path(tmp) / "ws_port.json",
                {
                    "host": "127.0.0.1",
                    "port": 13939,
                    "ts": now_ms,
                    "launch_session": "launch",
                    "signature": signature,
                },
            )
            with mock.patch.object(services, "USER_DIR", Path(tmp)):
                self.assertTrue(manager._valid_backend_port_file())

    def test_backend_shutdown_file_matches_control_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = services.ServiceManager()
            manager.launch_session = "launch"
            manager.ws_token = "secret"
            manager.backend_proc = FakeProcess(4100, exits_on_wait=True)
            with mock.patch.object(services, "USER_DIR", Path(tmp)):
                manager.stop_backend_only()
                payload = json.loads(
                    (Path(tmp) / "backend_control.json").read_text(encoding="utf-8")
                )
            self.assertEqual(payload["action"], "shutdown")
            self.assertTrue(
                services.validate_control_payload(payload, "launch", "secret")
            )


class LifecycleTests(unittest.TestCase):
    def test_pet_ready_requires_signed_visible_media_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = services.ServiceManager()
            manager.launch_session = "renderer-session"
            manager.ws_token = "renderer-token"
            manager.electron_proc = FakeProcess(100)
            path = Path(tmp) / "pet_control.json"
            with mock.patch.object(services, "USER_DIR", Path(tmp)):
                invalid = services._signed_control_payload(
                    "renderer_ready",
                    manager.launch_session,
                    manager.ws_token,
                    state="visible",
                    media_count=0,
                )
                atomic_write_json(path, invalid)
                self.assertFalse(manager._wait_pet_ready(timeout=0.01))

                ready = services._signed_control_payload(
                    "renderer_ready",
                    manager.launch_session,
                    manager.ws_token,
                    state="visible",
                    media_count=3,
                )
                atomic_write_json(path, ready)
                self.assertTrue(manager._wait_pet_ready(timeout=0.1))

    def test_same_secret_and_session_are_passed_to_both_children(self):
        manager = services.ServiceManager()
        manager._new_launch_identity()
        manager.set_launch_display_point(-800, 600)
        backend = FakeProcess(101)
        electron = FakeProcess(102)
        with (
            mock.patch.object(services, "popen_hidden", side_effect=[backend, electron]) as popen,
            mock.patch.object(services, "resolve_backend_python", return_value=Path(sys.executable)),
            mock.patch.object(services, "resolve_electron", return_value=Path(sys.executable)),
            mock.patch.object(services, "write_pet_command"),
            mock.patch.object(manager, "_start_heartbeat_locked"),
        ):
            self.assertTrue(manager.start_backend())
            self.assertTrue(manager.start_electron())

        backend_env = popen.call_args_list[0].kwargs["env"]
        electron_env = popen.call_args_list[1].kwargs["env"]
        self.assertEqual(backend_env["MIKU_LAUNCH_SESSION"], manager.launch_session)
        self.assertEqual(electron_env["MIKU_LAUNCH_SESSION"], manager.launch_session)
        self.assertEqual(backend_env["MIKU_WS_TOKEN"], manager.ws_token)
        self.assertEqual(electron_env["MIKU_WS_TOKEN"], manager.ws_token)
        self.assertEqual(backend_env["MIKU_EXPECT_LAUNCHER_HEARTBEAT"], "1")
        self.assertEqual(backend_env["MIKU_EMOTION_RECOGNITION_ENABLED"], "1")
        self.assertEqual(electron_env["MIKU_EXPECT_LAUNCHER_HEARTBEAT"], "0")
        self.assertEqual(electron_env["MIKU_LAUNCH_DISPLAY_X"], "-800")
        self.assertEqual(electron_env["MIKU_LAUNCH_DISPLAY_Y"], "600")
        self.assertNotIn("MIKU_LAUNCHER_PID", backend_env)
        self.assertNotIn("MIKU_LAUNCHER_STARTED_AT", electron_env)
        self.assertGreaterEqual(len(manager.ws_token), 32)

    def test_signed_heartbeat_is_atomic_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = services.ServiceManager()
            manager.launch_session = "heartbeat-session"
            manager.ws_token = "heartbeat-token"
            path = Path(tmp) / "launcher_heartbeat.json"
            with (
                mock.patch.object(services, "USER_DIR", Path(tmp)),
                mock.patch.object(services, "_HEARTBEAT_INTERVAL_SEC", 0.01),
            ):
                with manager._lifecycle_lock:
                    manager._start_heartbeat_locked()
                first = read_json(path)
                self.assertEqual(first["action"], "heartbeat")
                self.assertTrue(
                    services.validate_control_payload(
                        first,
                        "heartbeat-session",
                        "heartbeat-token",
                    )
                )
                self.assertEqual(list(Path(tmp).glob(".launcher_heartbeat.json.*.tmp")), [])

                deadline = time.monotonic() + 0.5
                while time.monotonic() < deadline:
                    latest = read_json(path)
                    if latest.get("ts", 0) > first["ts"]:
                        break
                    time.sleep(0.01)
                self.assertGreater(latest["ts"], first["ts"])

                with manager._lifecycle_lock:
                    manager._stop_heartbeat_locked()
                self.assertIsNone(manager._heartbeat_thread)
                self.assertFalse(path.exists())
                time.sleep(0.03)
                self.assertFalse(path.exists())

    def test_language_command_is_signed_for_the_current_child(self):
        manager = services.ServiceManager()
        manager._new_launch_identity()
        manager.electron_proc = FakeProcess(103)
        with mock.patch.object(services, "write_pet_command") as write:
            self.assertTrue(manager.set_language("ja"))
        write.assert_called_once_with(
            "language",
            lang="ja",
            launch_session=manager.launch_session,
            token=manager.ws_token,
        )
        self.assertFalse(manager.set_language("invalid"))

    def test_service_status_is_localized(self):
        manager = services.ServiceManager()
        with mock.patch.object(services, "IS_PORTABLE", False):
            self.assertEqual(
                manager.status_text("en"),
                "[Development] Backend: Stopped  ·  Pet: Stopped",
            )
        self.assertIn("バックエンド", manager.status_text("ja"))

    def test_stop_cancels_backend_readiness_wait_without_waiting_for_timeout(self):
        manager = services.ServiceManager()
        backend = FakeProcess(104, exits_on_wait=True)
        wait_entered = threading.Event()
        results: list[bool] = []

        def start_backend():
            manager.backend_proc = backend
            return True

        def wait_backend(*_args, cancel_event=None, expected_proc=None, **_kwargs):
            self.assertIs(expected_proc, backend)
            self.assertIs(cancel_event, manager._startup_cancel)
            wait_entered.set()
            self.assertTrue(cancel_event.wait(2))
            return False

        with (
            mock.patch.object(manager, "_start_backend_locked", side_effect=start_backend),
            mock.patch.object(manager, "_wait_backend_ready", side_effect=wait_backend),
            mock.patch.object(manager, "_start_electron_locked") as start_electron,
            mock.patch.object(manager, "_write_backend_shutdown") as shutdown,
            mock.patch.object(services, "write_pet_command"),
            mock.patch.object(services, "_force_kill_tree") as force_kill,
        ):
            starter = threading.Thread(
                target=lambda: results.append(manager.start_all())
            )
            stopper = threading.Thread(target=manager.stop_all)
            starter.start()
            self.assertTrue(wait_entered.wait(1))

            started = time.monotonic()
            stopper.start()
            stopper.join(1)
            elapsed = time.monotonic() - started
            self.assertFalse(stopper.is_alive())
            self.assertLess(elapsed, 1.0)

            starter.join(1)
            self.assertFalse(starter.is_alive())
            self.assertEqual(results, [False])
            self.assertIsNone(manager.backend_proc)
            start_electron.assert_not_called()
            shutdown.assert_called_once()
            force_kill.assert_not_called()

    def test_cancel_signal_alone_reclaims_the_starting_backend(self):
        manager = services.ServiceManager()
        backend = FakeProcess(106, exits_on_wait=True)
        wait_entered = threading.Event()
        results: list[bool] = []

        def start_backend():
            manager.backend_proc = backend
            return True

        def wait_backend(*_args, cancel_event=None, **_kwargs):
            wait_entered.set()
            self.assertTrue(cancel_event.wait(2))
            return False

        with (
            mock.patch.object(manager, "_start_backend_locked", side_effect=start_backend),
            mock.patch.object(manager, "_wait_backend_ready", side_effect=wait_backend),
            mock.patch.object(manager, "_start_electron_locked") as start_electron,
            mock.patch.object(manager, "_write_backend_shutdown") as shutdown,
            mock.patch.object(manager, "_stop_heartbeat_locked") as stop_heartbeat,
            mock.patch.object(services, "write_pet_command"),
        ):
            starter = threading.Thread(
                target=lambda: results.append(manager.start_all())
            )
            starter.start()
            self.assertTrue(wait_entered.wait(1))
            manager.cancel_startup()
            starter.join(1)

        self.assertFalse(starter.is_alive())
        self.assertEqual(results, [False])
        self.assertIsNone(manager.backend_proc)
        start_electron.assert_not_called()
        shutdown.assert_called_once()
        stop_heartbeat.assert_called_once()

    def test_stop_waits_for_failed_start_to_reclaim_its_detached_process(self):
        manager = services.ServiceManager()
        backend = FakeProcess(105)
        reclaim_entered = threading.Event()
        release_reclaim = threading.Event()

        def start_backend():
            manager.backend_proc = backend
            return True

        def reclaim(proc, **_kwargs):
            self.assertIs(proc, backend)
            reclaim_entered.set()
            self.assertTrue(release_reclaim.wait(2))

        with (
            mock.patch.object(manager, "_start_backend_locked", side_effect=start_backend),
            mock.patch.object(manager, "_wait_backend_ready", return_value=False),
            mock.patch.object(manager, "_stop_backend_process", side_effect=reclaim),
            mock.patch.object(manager, "_stop_heartbeat_locked"),
            mock.patch.object(services, "write_pet_command"),
        ):
            starter = threading.Thread(target=manager.start_all)
            stopper = threading.Thread(target=manager.stop_all)
            starter.start()
            self.assertTrue(reclaim_entered.wait(1))
            stopper.start()
            stopper.join(0.1)
            self.assertTrue(stopper.is_alive())

            release_reclaim.set()
            starter.join(1)
            stopper.join(1)
            self.assertFalse(starter.is_alive())
            self.assertFalse(stopper.is_alive())
            self.assertIsNone(manager.backend_proc)

    def test_stale_pid_file_is_never_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "backend.pid"
            pid_path.write_text("99999", encoding="utf-8")
            manager = services.ServiceManager()
            with (
                mock.patch.object(services, "USER_DIR", Path(tmp)),
                mock.patch.object(services, "_force_kill_tree") as kill,
            ):
                manager.stop_backend_only()
            kill.assert_not_called()
            self.assertEqual(pid_path.read_text(encoding="utf-8"), "99999")

    def test_forced_kill_only_targets_tracked_process(self):
        manager = services.ServiceManager()
        proc = FakeProcess(4242)
        with (
            mock.patch.object(services, "_wait_for_exit", side_effect=[False, True]),
            mock.patch.object(services, "_force_kill_tree", return_value=True) as kill,
        ):
            manager._force_tracked_process(proc, "后端")
        kill.assert_called_once_with(4242)
        self.assertTrue(proc.terminate_called or proc.kill_called or services.os.name == "nt")


if __name__ == "__main__":
    unittest.main()
