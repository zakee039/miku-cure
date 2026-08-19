from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from core import envcheck  # noqa: E402


class _BlockingProbe:
    def __init__(self, cancelled: threading.Event) -> None:
        self.args = ["python", "-c", "probe"]
        self.returncode = None
        self._cancelled = cancelled
        self.terminated = False
        self.killed = False

    def communicate(self, timeout=None):
        if self.terminated or self.killed:
            self.returncode = -1
            return "", ""
        self._cancelled.set()
        raise subprocess.TimeoutExpired(self.args, timeout)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class EnvironmentCancellationTests(unittest.TestCase):
    def test_dependency_probe_terminates_when_worker_is_interrupted(self):
        cancelled = threading.Event()
        probe = _BlockingProbe(cancelled)
        with mock.patch.object(envcheck, "popen_hidden", return_value=probe):
            with self.assertRaises(envcheck.EnvCheckCancelled):
                envcheck._dependency_probe(
                    sys.executable,
                    cancelled=cancelled.is_set,
                )
        self.assertTrue(probe.terminated)
        self.assertFalse(probe.killed)


if __name__ == "__main__":
    unittest.main()
