"""Optional headless Qt smoke test for eleven independent controls.

Run on Windows with PySide6 and QT_QPA_PLATFORM=offscreen. In environments
without PySide6, the DSP tests still work and this test is skipped.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 not installed")
class GuiIntensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        filename = Path(__file__).resolve().parent.parent / "main.pyw"
        loader = SourceFileLoader("eq_gui_for_tests", str(filename))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        gui = importlib.util.module_from_spec(spec)
        loader.exec_module(gui)
        cls.gui = gui
        cls.app = QApplication.instance() or QApplication([])

    def test_independent_buttons_and_live_state(self):
        with patch.object(self.gui.Window, "startup_check", lambda self: None):
            window = self.gui.Window()
        try:
            window.show()
            self.app.processEvents()
            self.assertEqual(len(window.band_intensity_buttons), 10)
            self.assertEqual(window.preamp_intensity_button.text(), "×1")
            self.assertEqual([b.text() for b in window.band_intensity_buttons], ["×1"] * 10)
            for slider, button in zip(window.bands, window.band_intensity_buttons):
                self.assertEqual(len(button.menu().actions()), 5)
                center_slider = slider.mapToGlobal(slider.rect().center()).x()
                center_button = button.mapToGlobal(button.rect().center()).x()
                self.assertLessEqual(abs(center_slider - center_button), 2)
            before_preset = window.settings.preset_id
            before_gains = window.settings.gains_db
            window.change_intensity(None, 0.25, window.preamp_intensity_button)
            window.change_intensity(3, 4.0, window.band_intensity_buttons[3])
            self.assertEqual(window.settings.preamp_intensity, 0.25)
            self.assertEqual(window.settings.band_intensities[3], 4.0)
            self.assertEqual(window.settings.band_intensities[2], 1.0)
            self.assertEqual(window.settings.gains_db, before_gains)
            self.assertEqual(window.settings.preset_id, before_preset)
            self.assertEqual(window.preamp_intensity_button.text(), "×¼")
            self.assertEqual(window.band_intensity_buttons[3].text(), "×4")
            window.choose_preset(window.preset.findData("TECHNO"))
            self.assertEqual(window.settings.preamp_intensity, 0.25)
            self.assertEqual(window.settings.band_intensities[3], 4.0)
            self.assertEqual(window.settings.preset_id, "TECHNO")
        finally:
            window.write_timer.stop()
            window.close()


if __name__ == "__main__":
    unittest.main()
