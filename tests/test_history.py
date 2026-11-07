"""History snapshots preserve all sound settings; undo/redo are bounded."""
import unittest
from dataclasses import replace

from equalizer import Settings
from history import AudioState, EditHistory


class EditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.original = Settings(True, "DEFAULT", 1.0, (0.0,) * 10)
        self.custom = Settings(False, "CUSTOM", 1.0, (0.0,) * 10)
        self.initial = AudioState(self.original, self.custom)
        self.history = EditHistory(capacity=3)

    def test_single_step_undo_redo(self):
        changed = AudioState(replace(self.original, gains_db=(8.0,) + (0.0,) * 9), self.custom)
        self.assertTrue(self.history.record(self.initial, changed))
        self.assertEqual(self.history.undo(changed), self.initial)
        self.assertEqual(self.history.redo(self.initial), changed)

    def test_noop_does_not_record_or_invalidate_redo(self):
        second = AudioState(replace(self.original, preamp_intensity=2), self.custom)
        self.history.record(self.initial, second)
        self.assertEqual(self.history.undo(second), self.initial)
        self.assertFalse(self.history.record(self.initial, self.initial))
        self.assertTrue(self.history.can_redo)

    def test_new_edit_after_undo_invalidates_redo(self):
        second = AudioState(replace(self.original, preamp_linear=.5), self.custom)
        third = AudioState(replace(self.original, preamp_linear=1.5), self.custom)
        self.history.record(self.initial, second)
        self.history.undo(second)
        self.history.record(self.initial, third)
        self.assertFalse(self.history.can_redo)
        self.assertEqual(self.history.undo(third), self.initial)

    def test_capacity_and_order(self):
        cur = self.initial
        for value in (.5, .6, .7, .8):
            nxt = AudioState(replace(self.original, preamp_linear=value), self.custom)
            self.history.record(cur, nxt)
            cur = nxt
        self.assertEqual(self.history.undo_count, 3)
        self.assertEqual(self.history.undo(cur).settings.preamp_linear, .7)
        self.assertEqual(self.history.undo_count, 2)

    def test_settings_and_custom_both_restored(self):
        updated_custom = replace(self.custom, gains_db=(11.0,) + (0.0,) * 9)
        changed = AudioState(replace(self.original, preset_id="CUSTOM"), updated_custom)
        self.history.record(self.initial, changed)
        previous = self.history.undo(changed)
        self.assertEqual(previous.custom, self.custom)
        self.assertEqual(previous.settings.preset_id, "DEFAULT")

    def test_clear_after_deleting_profile(self):
        changed = AudioState(replace(self.original, preset_id="CUSTOM"), self.custom)
        self.history.record(self.initial, changed)
        self.history.clear()
        self.assertFalse(self.history.can_undo)
        self.assertIsNone(self.history.undo(changed))

    def test_enabled_and_all_multipliers_in_snapshot(self):
        updated = replace(
            self.original, enabled=False, preamp_intensity=4,
            band_intensities=(.25, .5, 1, 2, 4) * 2,
        )
        changed = AudioState(updated, self.custom)
        self.history.record(self.initial, changed)
        self.assertEqual(self.history.redo(self.history.undo(changed)), changed)


if __name__ == "__main__":
    unittest.main()
