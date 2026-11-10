"""Headless Qt tests for neutralizing sliders by double-clicking."""
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
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 not installed")
class GuiNeutralResetTests(unittest.TestCase):
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
        self.window.connection_timer.stop()
        self.window.close()
        for p in reversed(self.patches):
            p.stop()

    def test_all_ten_band_double_clicks_reset_to_zero(self):
        w = self.window
        for i, slider in enumerate(w.bands):
            # Make each band non-neutral, then double-click directly on its rail.
            w.edit_band(i, 7.0)
            slider.set_value(7.0)
            QTest.mouseDClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(15, 130))
            self.app.processEvents()
            self.assertEqual(slider.value, 0.0, f"band {i} widget")
            self.assertEqual(w.settings.gains_db[i], 0.0, f"band {i} audio")
        self.assertEqual(w.settings.gains_db, (0.0,) * 10)

    def test_preamp_double_click_is_unity_gain_and_undoable(self):
        w = self.window
        w.edit_preamp(.5)
        w.preamp.set_value(.5)
        before = w.audio_state()
        n = w.history.undo_count
        QTest.mouseDClick(w.preamp, Qt.MouseButton.LeftButton, pos=QPoint(25, 30))
        self.app.processEvents()
        self.assertEqual(w.preamp.value, 1.0)
        self.assertEqual(w.settings.preamp_linear, 1.0)
        self.assertEqual(w.history.undo_count, n + 1)
        w.undo_edit()
        self.assertEqual(w.audio_state(), before)
        self.assertEqual(w.preamp.value, .5)
        w.redo_edit()
        self.assertEqual(w.preamp.value, 1.0)

    def test_first_click_and_double_click_are_one_undo_action(self):
        w = self.window
        w.edit_band(0, 6.0)
        slider = w.bands[0]
        slider.set_value(6.0)
        before = w.audio_state()
        n = w.history.undo_count
        # Qt emits a normal press/release before its double-click event.
        # That first click must not create an extra undo step.
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(15, 30))
        self.assertNotEqual(w.settings.gains_db[0], before.settings.gains_db[0])
        QTest.mouseDClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(15, 30))
        self.app.processEvents()
        self.assertEqual(w.settings.gains_db[0], 0.0)
        self.assertEqual(w.history.undo_count, n + 1)
        w.undo_edit()
        self.assertEqual(w.audio_state(), before)
        w.redo_edit()
        self.assertEqual(w.settings.gains_db[0], 0.0)

    def test_neutral_values_do_not_create_extra_history(self):
        w = self.window
        w.edit_preamp(1.0)
        w.preamp.set_value(1.0)
        n = w.history.undo_count
        QTest.mouseDClick(w.preamp, Qt.MouseButton.LeftButton, pos=QPoint(25, 90))
        self.app.processEvents()
        self.assertEqual(w.history.undo_count, n)
        self.assertEqual(w.settings.preamp_linear, 1.0)

    def test_intensity_and_other_bands_are_untouched(self):
        w = self.window
        w.change_intensity(0, 4.0, w.band_intensity_buttons[0])
        w.change_intensity(None, 2.0, w.preamp_intensity_button)
        w.edit_band(0, 11.0)
        w.edit_band(1, -4.0)
        w.bands[0].set_value(11.0)
        w.bands[1].set_value(-4.0)
        QTest.mouseDClick(w.bands[0], Qt.MouseButton.LeftButton, pos=QPoint(15, 170))
        self.app.processEvents()
        self.assertEqual(w.settings.gains_db[0], 0.0)
        self.assertEqual(w.settings.gains_db[1], -4.0)
        self.assertEqual(w.settings.band_intensities[0], 4.0)
        self.assertEqual(w.settings.preamp_intensity, 2.0)


if __name__ == "__main__":
    unittest.main()
