"""Qt lifecycle smoke tests: tray mode, exit failure, and safe explicit quit."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from dataclasses import replace
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 not installed")
class GuiTrayLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = "eq_gui_for_tests"
        gui = sys.modules.get(name)
        if gui is None:
            path = Path(__file__).resolve().parent.parent / "main.pyw"
            loader = SourceFileLoader(name, str(path))
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
        for item in self.patches:
            item.start()
        self.window = gui.Window()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.write_timer.stop()
        self.window.connection_timer.stop()
        self.window.tray_controller = None
        self.window.close()
        for item in reversed(self.patches):
            item.stop()

    def test_close_to_tray_hides_but_preserves_active_sound(self):
        w = self.window
        w.toggle(True)
        before = w.settings
        icon = SimpleNamespace(isVisible=lambda: True)
        w.tray_controller = SimpleNamespace(icon=icon, refresh=Mock())
        self.assertTrue(w.isVisible())
        self.assertFalse(w.close())
        self.assertFalse(w.isVisible())
        self.assertEqual(w.settings, before)
        self.assertEqual(w.history.undo_count, 1)
        w.show_window()
        self.assertTrue(w.isVisible())
        self.assertFalse(w.close())
        self.assertFalse(w.isVisible())
        # No balloon/toast is sent on any close-to-tray transition.
        self.assertFalse(hasattr(w.tray_controller, "notify_hidden"))

    def test_exit_failure_keeps_process_and_eq_running(self):
        w = self.window
        w.toggle(True)
        before = w.settings
        error = self.gui.lifecycle.ShutdownError("APO write denied")
        with patch.object(self.gui.lifecycle, "disable_and_persist", side_effect=error), \
             patch.object(self.gui, "make_dialog") as dialog:
            self.assertFalse(w.request_exit())
        dialog.return_value.exec.assert_called_once()
        self.assertTrue(w.isVisible())
        self.assertFalse(w._exit_completed)
        self.assertEqual(w.settings, before)

    def test_explicit_exit_writes_off_and_only_then_quits(self):
        w = self.window
        w.toggle(True)
        events = []
        def stop(settings, custom, library):
            events.append(("disabled", settings.enabled))
            return replace(settings, enabled=False)
        with patch.object(self.gui.lifecycle, "disable_and_persist", side_effect=stop), \
             patch.object(self.gui, "QTimer") as timer:
            self.assertTrue(w.request_exit())
            timer.singleShot.assert_called_once()
        self.assertEqual(events, [("disabled", True)])
        self.assertTrue(w._exit_completed)
        self.assertFalse(w.settings.enabled)
        self.assertFalse(w.switch.checked)

    def test_tray_menu_toggles_and_selects_presets(self):
        w = self.window
        # Qt's offscreen platform has no actual Windows notification area;
        # QSystemTrayIcon can still build the menu and its actions in Qt.
        from tray_ui import TrayController
        tray = TrayController(w)
        try:
            self.assertTrue(tray.power_action.isCheckable())
            self.assertIs(tray.window, w)
            self.assertEqual(tray.undo_action.text(), "Отменить")
            self.assertEqual(tray.redo_action.text(), "Повторить")
            self.assertEqual(tray.exit_action.text(), "Выход")
            self.assertFalse(hasattr(tray, "notify_hidden"))
            tray._toggle(True)
            self.assertTrue(w.settings.enabled)
            self.assertTrue(w.switch.checked)
            tray.refresh()
            self.assertTrue(tray.power_action.isChecked())
            tray._populate_presets()
            self.assertTrue(any(a.text() == "TECHNO" or "Techno" in a.text()
                                for a in tray.presets_menu.actions()))
            tray.select_preset("TECHNO")
            self.assertEqual(w.settings.preset_id, "TECHNO")
            tray._toggle(False)
            self.assertFalse(w.settings.enabled)
        finally:
            tray.hide()

    def test_tray_undo_and_redo_work_with_hidden_window(self):
        w = self.window
        from tray_ui import TrayController
        start = w.settings.gains_db[0]
        w.edit_band(0, 8.0)
        tray = TrayController(w)
        try:
            w.hide()
            tray.refresh()
            self.assertTrue(tray.undo_action.isEnabled())
            tray.undo_action.trigger()
            self.assertFalse(w.isVisible())
            self.assertEqual(w.settings.gains_db[0], start)
            tray.refresh()
            self.assertTrue(tray.redo_action.isEnabled())
            tray.redo_action.trigger()
            self.assertFalse(w.isVisible())
            self.assertEqual(w.settings.gains_db[0], 8.0)
        finally:
            tray.hide()

    def test_singleton_show_window_does_not_reset_audio(self):
        w = self.window
        w.edit_band(0, 8)
        before = w.audio_state()
        w.hide()
        w.show_window()
        self.assertTrue(w.isVisible())
        self.assertEqual(w.audio_state(), before)


if __name__ == "__main__":
    unittest.main()
