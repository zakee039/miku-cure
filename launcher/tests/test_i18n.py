from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from core.i18n import (  # noqa: E402
    TEXTS,
    environment_summary,
    get_texts,
    translate_environment_detail,
    translate_progress,
)


class LauncherTranslationTests(unittest.TestCase):
    def test_all_languages_have_the_same_complete_contract(self):
        expected_keys = set(TEXTS["zh"])
        expected_progress = set(TEXTS["zh"]["progress"])
        expected_env_names = set(TEXTS["zh"]["env_names"])
        for language in ("ja", "en"):
            self.assertEqual(set(TEXTS[language]), expected_keys)
            self.assertEqual(set(TEXTS[language]["progress"]), expected_progress)
            self.assertEqual(set(TEXTS[language]["env_names"]), expected_env_names)
            self.assertEqual(len(TEXTS[language]["nav"]), 4)
            self.assertEqual(len(TEXTS[language]["log_tabs"]), 3)
            self.assertEqual(len(TEXTS[language]["close_actions"]), 3)
            self.assertEqual(len(TEXTS[language]["folders"]), 3)

    def test_unknown_language_falls_back_to_chinese(self):
        self.assertIs(get_texts("unknown"), TEXTS["zh"])
        self.assertIs(get_texts([]), TEXTS["zh"])

    def test_dynamic_progress_and_environment_summary_are_localized(self):
        message = "正在启动后端服务…"
        self.assertEqual(translate_progress("zh", message), message)
        self.assertEqual(translate_progress("en", message), "Starting backend service…")

        report = SimpleNamespace(
            items=[
                SimpleNamespace(ok=True),
                SimpleNamespace(ok=False),
            ],
            all_required_ok=False,
        )
        self.assertEqual(
            environment_summary("en", report),
            "Environment check 1/2 passed · Problems found",
        )
        self.assertIn("問題あり", environment_summary("ja", report))
        self.assertEqual(
            translate_environment_detail("en", "缺少 C:/runtime"),
            "Missing C:/runtime",
        )


if __name__ == "__main__":
    unittest.main()
