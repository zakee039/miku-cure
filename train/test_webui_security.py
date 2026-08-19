import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import webui


class TrainingWebUiSecurityTests(unittest.TestCase):
    def test_origin_must_be_loopback(self):
        self.assertTrue(webui._is_allowed_origin("http://127.0.0.1:8000"))
        self.assertTrue(webui._is_allowed_origin("http://localhost:8000"))
        self.assertFalse(webui._is_allowed_origin("https://example.com"))
        self.assertFalse(webui._is_allowed_origin(None))

    def test_dataset_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "safe.csv").write_text("emotion,pixels\n", encoding="utf-8")
            with patch.object(webui, "DATASETS_DIR", root):
                self.assertEqual(webui._resolve_dataset("safe.csv"), root / "safe.csv")
                with self.assertRaises(ValueError):
                    webui._resolve_dataset("../secret.csv")
                with self.assertRaises(ValueError):
                    webui._resolve_dataset("missing.csv")

    def test_hyperparameters_are_bounded(self):
        self.assertEqual(
            webui._bounded_integer(64, minimum=1, maximum=4096, name="Batch"),
            64,
        )
        with self.assertRaises(ValueError):
            webui._bounded_integer(1.5, minimum=1, maximum=4096, name="Batch")
        with self.assertRaises(ValueError):
            webui._bounded_number(float("nan"), minimum=0, maximum=1, name="LR")

    def test_shutdown_terminates_only_the_tracked_training_process(self):
        process = Mock()
        process.poll.return_value = None
        webui.training_process = process
        webui.current_training_model = "cnn"
        webui.active_connections.add(Mock())

        with patch.object(webui, "_terminate_process_tree") as terminate:
            asyncio.run(webui._shutdown_training())

        terminate.assert_called_once_with(process)
        self.assertIsNone(webui.training_process)
        self.assertIsNone(webui.current_training_model)
        self.assertFalse(webui.active_connections)


if __name__ == "__main__":
    unittest.main()
