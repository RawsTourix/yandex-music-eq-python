"""Independent preamp and ten band-intensity modes."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from equalizer import (
    COMMON_SAMPLE_RATES, INTENSITIES, Settings, SettingsError,
    _biquad, generate_apo_config, load_library, load_settings,
    preset_settings, save_settings,
)


class IntensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()
        cls.base = Settings(True, "CUSTOM", 0.5, (6.0, -3.0) + (0.0,) * 8)

    def test_modes_and_defaults(self):
        self.assertEqual(INTENSITIES, (0.25, 0.5, 1.0, 2.0, 4.0))
        s = Settings.from_dict(
            {"enabled": True, "presetId": "CUSTOM", "preampLinear": 1,
             "gainsDb": [0]*10}, self.library["frequenciesHz"]
        )
        self.assertEqual(s.preamp_intensity, 1.0)
        self.assertEqual(s.band_intensities, (1.0,) * 10)

    def test_migrate_legacy_global_intensity(self):
        old = {"enabled": True, "presetId": "CUSTOM",
               "preampLinear": 0.5, "gainsDb": [6]*10, "intensity": 2}
        s = Settings.from_dict(old, self.library["frequenciesHz"])
        self.assertEqual(s.preamp_intensity, 2)
        self.assertEqual(s.band_intensities, (2,) * 10)
        self.assertNotIn("intensity", s.to_dict())
        self.assertEqual(s.to_dict()["bandIntensities"], [2] * 10)

    def test_new_controls_override_legacy(self):
        data = {**self.base.to_dict(), "intensity": 4}
        result = Settings.from_dict(data, self.library["frequenciesHz"])
        self.assertEqual(result.preamp_intensity, 1)
        self.assertEqual(result.band_intensities, (1,) * 10)

    def test_mixed_bands_emit_independent_cascades(self):
        factors = (4.0, 0.25, 2.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        gains = (6.0, -3.0, 2.0, 0.1, 5.0) + (0.0,) * 5
        cfg = generate_apo_config(
            replace(self.base, preamp_intensity=0.5,
                    gains_db=gains, band_intensities=factors), self.library
        )
        # 4 copies of 60 Hz, 1 reduced 170 Hz, 2 of 310 Hz,
        # 1 reduced 600 Hz, 1 of 1000 Hz: 9 per sample rate.
        self.assertEqual(cfg.count("ON IIR Order 2"), len(COMMON_SAMPLE_RATES) * 9)
        block = cfg.split("If: sampleRate == 44100\n", 1)[1].split("ElseIf:", 1)[0]
        entries = [line.strip().split("Coefficients ", 1)[1]
                   for line in block.splitlines() if "ON IIR Order 2" in line]
        self.assertEqual(entries[0:4], [entries[0]] * 4)
        self.assertNotEqual(entries[4], entries[0])
        self.assertEqual(entries[5], entries[6])
        self.assertIn("Gain -0.75 dB", cfg)
        # Fractional gain must retain precision rather than rounding to 0.0 dB.
        self.assertIn("Gain 0.05 dB", cfg)
        self.assertIn(f"Preamp: {20*math.log10(0.5)*0.5:.9f} dB", cfg)

    def test_preamp_is_independent(self):
        cfg1 = generate_apo_config(replace(self.base, preamp_intensity=1), self.library)
        cfg4 = generate_apo_config(replace(self.base, preamp_intensity=4), self.library)
        self.assertEqual(cfg1.count("ON IIR Order 2"), cfg4.count("ON IIR Order 2"))
        self.assertIn(f"Preamp: {20*math.log10(0.5)*4:.9f} dB", cfg4)

    def test_all_bands_x4(self):
        config = generate_apo_config(
            replace(self.base, band_intensities=(4.0,) * 10), self.library
        )
        self.assertEqual(config.count("ON IIR Order 2"), 8 * len(COMMON_SAMPLE_RATES))
        first = config.split("If: sampleRate == 44100\n", 1)[1].split("ElseIf:", 1)[0]
        self.assertEqual(first.count("ON IIR Order 2"), 8)

    def test_x2_is_not_single_twelve_db_biquad(self):
        factors = (2.0,) + (1.0,) * 9
        cfg = generate_apo_config(replace(
            self.base, band_intensities=factors, gains_db=(6.0,) + (0.0,) * 9
        ), self.library)
        self.assertNotEqual(_biquad("lowshelf", 60, 6, 44100),
                            _biquad("lowshelf", 60, 12, 44100))
        rate = cfg.split("If: sampleRate == 44100\n", 1)[1].split("ElseIf:", 1)[0]
        self.assertEqual(rate.count("ON IIR Order 2"), 2)

    def test_reject_invalid_modes_and_band_count(self):
        data = self.base.to_dict()
        for bad in (-1, 0, 0.1, 1.25, 8, float("nan"), "2", True):
            with self.subTest(bad=bad):
                self.assertRaises(
                    SettingsError, Settings.from_dict,
                    {**data, "preampIntensity": bad}, self.library["frequenciesHz"]
                )
                self.assertRaises(
                    SettingsError, Settings.from_dict,
                    {**data, "bandIntensities": [bad]+[1]*9},
                    self.library["frequenciesHz"]
                )
        self.assertRaises(
            SettingsError, Settings.from_dict,
            {**data, "bandIntensities": [1]*9}, self.library["frequenciesHz"]
        )

    def test_persistence_and_preset_independence(self):
        setting = replace(
            self.base, preamp_intensity=4,
            band_intensities=(0.25, 0.5, 1, 2, 4) * 2
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            save_settings(setting, path)
            contents = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(contents["preampIntensity"], 4)
            self.assertEqual(contents["bandIntensities"], [0.25, 0.5, 1, 2, 4] * 2)
            self.assertEqual(load_settings(self.library, path), setting)
            self.assertNotIn("intensity", contents)
        preset = preset_settings(self.library, "TECHNO", enabled=True)
        self.assertEqual(preset.preamp_intensity, 1)
        self.assertEqual(preset.band_intensities, (1,) * 10)

    def test_load_legacy_settings_json(self):
        legacy = self.base.to_dict()
        legacy.pop("preampIntensity")
        legacy.pop("bandIntensities")
        legacy["intensity"] = 0.5
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"settings.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            result = load_settings(self.library, path)
            self.assertEqual(result.preamp_intensity, 0.5)
            self.assertEqual(result.band_intensities, (0.5,) * 10)

    def test_disabled_bypasses_all_bands(self):
        cfg = generate_apo_config(
            replace(self.base, enabled=False, preamp_intensity=4,
                    band_intensities=(4.0,) * 10), self.library
        )
        self.assertNotIn("Preamp:", cfg)
        self.assertNotIn("ON IIR", cfg)


if __name__ == "__main__":
    unittest.main()
