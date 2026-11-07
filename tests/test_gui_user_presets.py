"""Headless Qt integration tests for named user presets in the real GUI."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 not installed")
class GuiUserPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = "eq_gui_for_tests"
        gui = sys.modules.get(name)
        if gui is None:
            filename = Path(__file__).resolve().parent.parent / "main.pyw"
            loader = SourceFileLoader(name, str(filename))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            gui = importlib.util.module_from_spec(spec)
            sys.modules[name] = gui
            loader.exec_module(gui)
        cls.gui = gui
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        gui = self.gui
        self.patches = [
            patch.object(gui.profiles, "load_user_presets", return_value={}),
            patch.object(gui.profiles, "save_user_presets", return_value=None),
            patch.object(gui.Window, "commit_settings", lambda self: None),
            patch.object(gui.Window, "startup_check", lambda self: None),
        ]
        for p in self.patches:
            p.start()
        self.window = gui.Window()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.write_timer.stop()
        self.window.close()
        for p in reversed(self.patches):
            p.stop()

    def test_save_restore_entire_profile(self):
        window = self.window
        window.edit_preamp(.5)
        window.edit_band(0, 12)
        window.edit_band(1, -11)
        window.change_intensity(None, 4.0, window.preamp_intensity_button)
        window.change_intensity(0, 4.0, window.band_intensity_buttons[0])
        window.change_intensity(1, .25, window.band_intensity_buttons[1])
        with patch.object(window, "_ask_preset_name", return_value="Super Bass"):
            self.assertTrue(window.save_preset_as())
        user_id = window.settings.preset_id
        self.assertIn(user_id, window.user_presets)
        self.assertEqual(window.preset.currentText(), "★ Super Bass")
        self.assertFalse(window.preset_dirty)

        window.preset.setCurrentIndex(window.preset.findData("TECHNO"))
        window.preset.setCurrentIndex(window.preset.findData(user_id))
        self.assertEqual(window.settings.preamp_linear, .5)
        self.assertEqual(window.settings.gains_db[0:2], (12, -11))
        self.assertEqual(window.settings.preamp_intensity, 4)
        self.assertEqual(window.settings.band_intensities[0:2], (4, .25))
        self.assertEqual(window.preamp_intensity_button.text(), "×4")
        self.assertEqual(window.band_intensity_buttons[1].text(), "×¼")

    def test_unsaved_edit_and_explicit_update(self):
        window = self.window
        with patch.object(window, "_ask_preset_name", return_value="Bass"):
            self.assertTrue(window.save_preset_as())
        user_id = window.settings.preset_id
        original = window.user_presets[user_id]["gainsDb"][0]
        window.edit_band(0, original + 1)
        self.assertTrue(window.preset_dirty)
        self.assertEqual(window.settings.preset_id, user_id)
        self.assertIn("*", window.preset_save_button.text())
        self.assertEqual(window.user_presets[user_id]["gainsDb"][0], original)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            window.preset.setCurrentIndex(window.preset.findData("TECHNO"))
        self.assertEqual(window.settings.preset_id, user_id)
        self.assertTrue(window.preset_dirty)
        self.assertTrue(window.update_user_preset())
        self.assertFalse(window.preset_dirty)
        self.assertEqual(window.user_presets[user_id]["gainsDb"][0], original + 1)

    def test_export_and_import_do_not_change_live_audio(self):
        window = self.window
        window.edit_band(0, 12)
        window.change_intensity(0, 4.0, window.band_intensity_buttons[0])
        with patch.object(window, "_ask_preset_name", return_value="Super Bass"):
            self.assertTrue(window.save_preset_as())
        before = window.settings
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"Super Bass.yeq.json"
            with patch.object(self.gui.QFileDialog, "getSaveFileName",
                              return_value=(str(output), "JSON")):
                window.export_current_preset()
            self.assertTrue(output.is_file())
            with patch.object(self.gui.QFileDialog, "getOpenFileName",
                              return_value=(str(output), "JSON")), \
                 patch.object(window, "_ask_preset_name",
                              return_value="Super Bass (import)"):
                window.import_user_preset()
        self.assertEqual(window.settings, before)
        self.assertIn("Super Bass (import)", [x["name"] for x in window.user_presets.values()])
        self.assertEqual(len(window.user_presets), 2)

    def test_rename_and_delete_preserves_sound(self):
        window = self.window
        window.edit_band(0, 12)
        with patch.object(window, "_ask_preset_name", return_value="Super Bass"):
            window.save_preset_as()
        user_id = window.settings.preset_id
        with patch.object(window, "_ask_preset_name", return_value="Deep Bass"):
            window.rename_user_preset()
        self.assertEqual(window.user_presets[user_id]["name"], "Deep Bass")
        before = window.settings.gains_db
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            window.delete_user_preset()
        self.assertNotIn(user_id, window.user_presets)
        self.assertEqual(window.settings.preset_id, "CUSTOM")
        self.assertEqual(window.settings.gains_db, before)

    def test_input_dialog_accept_enum_exists(self):
        self.assertEqual(QInputDialog.DialogCode.Accepted, 1)


if __name__ == "__main__":
    unittest.main()
