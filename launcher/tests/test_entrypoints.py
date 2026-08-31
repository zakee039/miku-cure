from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SourceEntrypointTests(unittest.TestCase):
    def test_source_launcher_precedes_stale_root_executable(self):
        script = (PROJECT_ROOT / "start.bat").read_text(encoding="utf-8-sig")
        source_launch = script.index(
            'start "" "%VENV%\\Scripts\\pythonw.exe" "%ROOT%launcher\\main.py"'
        )
        executable_launch = script.index(
            'start "" "%ROOT%MikuCure-Launcher.exe"'
        )
        self.assertLess(source_launch, executable_launch)

    def test_launcher_dashboard_exposes_safe_restart_sequence(self):
        source = (PROJECT_ROOT / "launcher" / "ui" / "main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("self.btn_restart.clicked.connect(self._restart_all)", source)
        self.assertIn("self._begin_stop(exit_after=False, restart_after=True)", source)
        self.assertIn("self._start_all(restarting=True)", source)
        self.assertIn('self._restart_spinner_frames = ("◐", "◓", "◑", "◒")', source)
        self.assertIn("self._restart_spinner_timer.start()", source)
        self.assertIn("self._restart_spinner_timer.stop()", source)
        self.assertLess(
            source.index("self._begin_stop(exit_after=False, restart_after=True)"),
            source.index("self._start_all(restarting=True)"),
        )


if __name__ == "__main__":
    unittest.main()
