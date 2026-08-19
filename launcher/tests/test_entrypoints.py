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


if __name__ == "__main__":
    unittest.main()
