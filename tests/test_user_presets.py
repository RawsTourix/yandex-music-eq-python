"""Portable named presets: data fidelity, isolation, validation and migration."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from equalizer import Settings, load_library, load_settings
from user_presets import (
    FORMAT, VERSION, UserPresetError, ensure_unique_name, export_preset,
    import_preset, load_user_presets, new_preset_id, normalized_name,
    preset_settings, save_user_presets, snapshot,
)


class UserPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()
        cls.settings = Settings(
            True, "CUSTOM", 0.5,
            (12.0, -10.0, -11.0, -11.5, -12.0, -10.5, -10.0, -9.5, -9.0, -8.5),
            4.0, (4.0, 2.0, .25, .25, .25, .25, .25, .25, .25, .25),
        )

    def test_full_snapshot_includes_all_multipliers(self):
        p = snapshot(self.settings, "Super Bass")
        self.assertEqual(p["preampLinear"], 0.5)
        self.assertEqual(len(p["gainsDb"]), 10)
        self.assertEqual(p["preampIntensity"], 4)
        self.assertEqual(p["bandIntensities"][0:3], [4, 2, .25])

    def test_user_collection_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "user_presets.json"
            identifier = new_preset_id()
            profiles = {identifier: snapshot(self.settings, "  Super Bass  ")}
            save_user_presets(profiles, path)
            self.assertEqual(load_user_presets(path), {
                identifier: snapshot(self.settings, "Super Bass"),
            })
            restored = preset_settings(load_user_presets(path)[identifier], identifier, False)
            self.assertEqual(restored.gains_db, self.settings.gains_db)
            self.assertEqual(restored.preamp_intensity, 4)
            self.assertEqual(restored.band_intensities, self.settings.band_intensities)
            self.assertFalse(restored.enabled)

    def test_multiple_profiles_and_rename(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "user_presets.json"
            one, two = new_preset_id(), new_preset_id()
            profiles = {one: snapshot(self.settings, "Bass"),
                        two: snapshot(replace(self.settings, preamp_linear=1.1), "Airy")}
            save_user_presets(profiles, path)
            self.assertEqual(len(load_user_presets(path)), 2)
            profiles[one]["name"] = "Deep Bass"
            save_user_presets(profiles, path)
            self.assertIn("Deep Bass", [x["name"] for x in load_user_presets(path).values()])

    def test_name_uniqueness_casefold_and_validation(self):
        p = {new_preset_id(): snapshot(self.settings, "Super Bass")}
        with self.assertRaises(UserPresetError):
            ensure_unique_name(p, "SUPER BASS")
        self.assertEqual(ensure_unique_name(p, "Another"), "Another")
        for value in ("", " \n ", "a"*65, "Foo\nBar", 23):
            with self.subTest(value=value):
                with self.assertRaises(UserPresetError):
                    normalized_name(value)

    def test_export_import_portable_full_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"Super Bass.yeq.json"
            original = snapshot(self.settings, "Super Bass")
            export_preset(original, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["format"], FORMAT)
            self.assertEqual(raw["version"], VERSION)
            self.assertEqual(import_preset(path), original)
            self.assertNotIn("presetId", raw["preset"])
            self.assertNotIn("enabled", raw["preset"])

    def test_corrupt_collection_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "user_presets.json"
            path.write_text("{broken", encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(UserPresetError):
                load_user_presets(path)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_import_does_not_modify_profiles(self):
        with tempfile.TemporaryDirectory() as d:
            collection = Path(d) / "user_presets.json"
            identifier = new_preset_id()
            save_user_presets({identifier: snapshot(self.settings, "Original")}, collection)
            old_bytes = collection.read_bytes()
            path = Path(d) / "bad.yeq.json"
            raw = {"format": FORMAT, "version": VERSION,
                   "preset": snapshot(self.settings, "Bad")}
            raw["preset"]["bandIntensities"] = [2] * 9
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(UserPresetError):
                import_preset(path)
            self.assertEqual(old_bytes, collection.read_bytes())

    def test_wrong_format_or_unexpected_fields_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"bad.json"
            for bad in (
                {"format": "other", "version": 1, "preset": snapshot(self.settings, "A")},
                {"format": FORMAT, "version": 999, "preset": snapshot(self.settings, "A")},
                {"format": FORMAT, "version": 1, "preset": {**snapshot(self.settings, "A"), "shell": "cmd"}},
            ):
                with self.subTest(bad=bad):
                    path.write_text(json.dumps(bad), encoding="utf-8")
                    with self.assertRaises(UserPresetError):
                        import_preset(path)

    def test_invalid_ranges_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bad.json"
            for key, value in (
                ("preampLinear", 30),
                ("preampIntensity", 3),
                ("gainsDb", [100] + [0]*9),
                ("bandIntensities", [0] + [1]*9),
            ):
                record = snapshot(self.settings, "A")
                record[key] = value
                path.write_text(json.dumps({"format": FORMAT,"version":1,"preset":record}),encoding="utf-8")
                with self.subTest(key=key), self.assertRaises(UserPresetError):
                    import_preset(path)

    def test_missing_user_preset_falls_back_to_custom_without_data_loss(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            data = {**self.settings.to_dict(), "presetId": new_preset_id()}
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_settings(self.library, path, user_preset_ids=())
            self.assertEqual(loaded.preset_id, "CUSTOM")
            self.assertEqual(loaded.gains_db, self.settings.gains_db)
            self.assertEqual(loaded.band_intensities, self.settings.band_intensities)

    def test_saved_user_selection_stays_selected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"settings.json"
            identifier=new_preset_id()
            path.write_text(
                json.dumps({**self.settings.to_dict(), "presetId": identifier}),
                encoding="utf-8",
            )
            result=load_settings(self.library, path, user_preset_ids={identifier})
            self.assertEqual(result.preset_id, identifier)

    def test_empty_collection_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_user_presets(Path(d)/"missing.json"), {})


if __name__ == "__main__":
    unittest.main()
