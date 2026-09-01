from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from launcher.build_pyinstaller import sanitize_build_path


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

    def test_launcher_builds_use_the_isolated_pyinstaller_wrapper(self):
        batch = (PROJECT_ROOT / "launcher" / "build.bat").read_text(
            encoding="utf-8"
        )
        package = (PROJECT_ROOT / "package_portable.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('"%PYTHON%" build_pyinstaller.py', batch)
        self.assertIn("Join-Path $launcherDir 'build_pyinstaller.py'", package)
        self.assertNotIn('"%PYTHON%" -m PyInstaller', batch)

    def test_build_path_removes_foreign_icu_but_keeps_system_icu(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            system32 = root / "Windows" / "System32"
            foreign = root / "foreign"
            ordinary = root / "ordinary"
            for directory in (system32, foreign, ordinary):
                directory.mkdir(parents=True)
            (system32 / "icuuc.dll").touch()
            (foreign / "icuuc.dll").touch()

            value = str(foreign) + ";" + str(system32) + ";" + str(ordinary)
            sanitized, removed = sanitize_build_path(
                value,
                system_root=str(root / "Windows"),
            )

            self.assertEqual(removed, [str(foreign)])
            self.assertEqual(sanitized, str(system32) + ";" + str(ordinary))


if __name__ == "__main__":
    unittest.main()
