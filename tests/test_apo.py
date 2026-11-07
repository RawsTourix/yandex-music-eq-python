"""Integration checks that run without Windows, admin rights, or PySide6."""

from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
import tempfile

import apo


class APOTests(TestCase):
    def test_missing_installation(self):
        with patch.object(apo, "config_directory", return_value=None):
            connected, text = apo.connection_status()
            self.assertFalse(connected)
            self.assertIn("не найден", text)

    def test_existing_include_is_not_endpoint_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "config.txt").write_text("Include: yandex-music-eq.txt\n", encoding="utf-8")
            (folder / apo.MANAGED_NAME).write_text("# test", encoding="utf-8")
            with patch.object(apo, "config_directory", return_value=folder):
                connected, text = apo.connection_status()
                self.assertTrue(connected)
                self.assertIn("не проверено", text)

    def test_include_missing_or_file_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "config.txt").write_text("Preamp: -3 dB\n", encoding="utf-8")
            with patch.object(apo, "config_directory", return_value=folder):
                self.assertIn("Не создан файл", apo.connection_status()[1])
                (folder / apo.MANAGED_NAME).write_text("# test", encoding="utf-8")
                self.assertIn("отсутствует строка", apo.connection_status()[1])
                self.assertFalse(apo.is_connected())