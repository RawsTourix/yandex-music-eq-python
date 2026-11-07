"""Headless Qt undo/redo and keyboard-action smoke tests."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 not installed")
class GuiHistoryTests(unittest.TestCase):
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

    def test_save_only_in_overflow_and_shortcut_mapping(self):
        w = self.window
        self.assertFalse(hasattr(w, "preset_save_button"))
        self.assertIn(w.action_save, w.preset_menu.actions())
        self.assertIn(w.action_undo, w.preset_menu.actions())
        self.assertIn(w.action_redo, w.preset_menu.actions())
        self.assertEqual(
            {shortcut.key().toString() for shortcut in w.shortcuts},
            {"Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z", "Ctrl+S",
             "Ctrl+Shift+S", "Ctrl+E", "Ctrl+O"},
        )
        self.assertFalse(w.action_undo.isEnabled())
        self.assertFalse(w.action_redo.isEnabled())

    def test_drag_is_one_undo_action(self):
        w = self.window
        original = w.audio_state()
        w.begin_slider_edit()
        for value in (2.0, 7.0, 11.0, 12.0):
            w.edit_band(0, value)
        w.end_slider_edit()
        self.assertEqual(w.history.undo_count, 1)
        self.assertEqual(w.settings.gains_db[0], 12)
        self.assertTrue(w.action_undo.isEnabled())
        w.undo_edit()
        self.assertEqual(w.audio_state(), original)
        self.assertFalse(w.action_undo.isEnabled())
        self.assertTrue(w.action_redo.isEnabled())
        w.redo_edit()
        self.assertEqual(w.settings.gains_db[0], 12)
        self.assertEqual(w.settings.preset_id, "CUSTOM")

    def test_multiplier_preset_and_toggle_are_undoable(self):
        w = self.window
        start = w.audio_state()
        w.change_intensity(None, 4.0, w.preamp_intensity_button)
        w.change_intensity(0, .25, w.band_intensity_buttons[0])
        w.choose_preset(w.preset.findData("TECHNO"))
        w.toggle(not w.settings.enabled)
        self.assertEqual(w.history.undo_count, 4)
        w.undo_edit()
        self.assertEqual(w.settings.enabled, start.settings.enabled)
        w.undo_edit()
        self.assertEqual(w.settings.preset_id, start.settings.preset_id)
        w.undo_edit()
        self.assertEqual(w.band_intensity_buttons[0].text(), "×1")
        w.undo_edit()
        self.assertEqual(w.audio_state(), start)
        for _ in range(4):
            w.redo_edit()
        self.assertEqual(w.settings.preamp_intensity, 4.0)
        self.assertEqual(w.settings.band_intensities[0], .25)
        self.assertEqual(w.settings.preset_id, "TECHNO")
        self.assertNotEqual(w.settings.enabled, start.settings.enabled)

    def test_profile_dirty_recomputed_after_undo(self):
        w = self.window
        with patch.object(w, "_ask_preset_name", return_value="Super Bass"):
            self.assertTrue(w.save_preset_as())
        profile_id = w.settings.preset_id
        original_gain = w.settings.gains_db[0]
        w.edit_band(0, original_gain + 2)
        self.assertTrue(w.preset_dirty)
        self.assertIn("*", w.preset.currentText())
        w.undo_edit()
        self.assertEqual(w.settings.preset_id, profile_id)
        self.assertFalse(w.preset_dirty)
        self.assertNotIn("*", w.preset.currentText())
        w.redo_edit()
        self.assertTrue(w.preset_dirty)
        self.assertIn("*", w.preset.currentText())
        w.action_save.trigger()
        self.assertFalse(w.preset_dirty)
        self.assertEqual(w.user_presets[profile_id]["gainsDb"][0], original_gain + 2)

    def test_keyboard_ctrl_z_y_and_new_edit_invalidates_redo(self):
        w = self.window
        w.activateWindow()
        w.setFocus()
        self.app.processEvents()
        initial = w.settings.preamp_intensity
        w.change_intensity(None, 2.0, w.preamp_intensity_button)
        QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(w.settings.preamp_intensity, initial)
        QTest.keyClick(w, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(w.settings.preamp_intensity, 2.0)
        w.undo_edit()
        w.change_intensity(None, 4.0, w.preamp_intensity_button)
        self.assertFalse(w.history.can_redo)

    def test_switch_preset_undo_restores_custom_values(self):
        w = self.window
        w.edit_band(0, 11)
        before = w.audio_state()
        w.choose_preset(w.preset.findData("TECHNO"))
        w.undo_edit()
        self.assertEqual(w.audio_state(), before)
        self.assertEqual(w.preset.currentData(), "CUSTOM")
        self.assertEqual(w.bands[0].value, 11)


if __name__ == "__main__":
    unittest.main()
