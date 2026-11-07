"""Ensure app exit disables Equalizer APO before returning success."""
import unittest
from dataclasses import replace
from unittest.mock import Mock

from equalizer import Settings
from lifecycle import ShutdownError, disable_and_persist


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            True, "CUSTOM", 0.5, (12.0, -8.0) + (0.0,) * 8,
            4.0, (4.0, 2.0) + (1.0,) * 8,
        )
        self.custom = replace(self.settings, enabled=False)
        self.library = {"test": True}

    def test_connected_applies_disabled_audio_before_save(self):
        order = []
        def apply(settings, library):
            order.append(("apo", settings.enabled, settings.gains_db))
            return True
        def save(settings, *, custom):
            order.append(("saved", settings.enabled, settings.band_intensities))
        result = disable_and_persist(
            self.settings, self.custom, self.library,
            is_connected=lambda: True, apply=apply, save=save,
        )
        self.assertFalse(result.enabled)
        self.assertEqual(result.gains_db, self.settings.gains_db)
        self.assertEqual(result.band_intensities, self.settings.band_intensities)
        self.assertEqual(result.preamp_intensity, 4.0)
        self.assertEqual(order[0][0], "apo")
        self.assertEqual(order[1][0], "saved")
        self.assertFalse(order[0][1])
        self.assertFalse(order[1][1])

    def test_disconnected_still_persists_disabled(self):
        apply = Mock()
        save = Mock()
        result = disable_and_persist(
            self.settings, self.custom, self.library,
            is_connected=lambda: False, apply=apply, save=save,
        )
        apply.assert_not_called()
        self.assertFalse(result.enabled)
        self.assertFalse(save.call_args[0][0].enabled)

    def test_failed_apo_will_never_claim_shutdown(self):
        save = Mock()
        with self.assertRaises(ShutdownError):
            disable_and_persist(
                self.settings, self.custom, self.library,
                is_connected=lambda: True, apply=lambda *_: False, save=save,
            )
        save.assert_not_called()

    def test_io_error_in_apo_blocks_shutdown_and_save(self):
        save = Mock()
        with self.assertRaises(ShutdownError):
            disable_and_persist(
                self.settings, self.custom, self.library,
                is_connected=lambda: True,
                apply=Mock(side_effect=PermissionError("no write permission")), save=save,
            )
        save.assert_not_called()

    def test_settings_save_failure_blocks_shutdown(self):
        with self.assertRaises(ShutdownError):
            disable_and_persist(
                self.settings, self.custom, self.library,
                is_connected=lambda: True, apply=lambda *_: True,
                save=Mock(side_effect=PermissionError("disk full")),
            )

    def test_already_disabled_still_flushes_bypass(self):
        apply = Mock(return_value=True)
        result = disable_and_persist(
            replace(self.settings, enabled=False), self.custom, self.library,
            is_connected=lambda: True, apply=apply, save=lambda *a, **k: None,
        )
        self.assertFalse(result.enabled)
        apply.assert_called_once()
        self.assertFalse(apply.call_args[0][0].enabled)


if __name__ == "__main__":
    unittest.main()
