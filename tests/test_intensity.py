"""Intensity modes: exact serial chains for x1/x2/x4, reduced approximations for fractions."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from equalizer import (
    COMMON_SAMPLE_RATES, INTENSITIES, Settings, SettingsError,
    _biquad, generate_apo_config, load_library, load_settings, save_settings,
)


class IntensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()
        cls.base = Settings(True, "CUSTOM", 0.5, (6.0,) + (0.0,) * 9)

    def test_modes(self):
        self.assertEqual(INTENSITIES, (0.25, 0.5, 1.0, 2.0, 4.0))

    def test_one_to_four_exact_coefficient_copies(self):
        for multiple in (1.0, 2.0, 4.0):
            with self.subTest(intensity=multiple):
                cfg = generate_apo_config(replace(self.base, intensity=multiple), self.library)
                self.assertEqual(cfg.count("ON IIR Order 2"), len(COMMON_SAMPLE_RATES) * int(multiple))
                # The same original filter coefficients repeat for each stage.
                first_rate_block = cfg.split("If: sampleRate == 44100\n", 1)[1].split("ElseIf:", 1)[0]
                actual = [line.strip().split("Coefficients ", 1)[1]
                          for line in first_rate_block.splitlines() if "ON IIR Order 2" in line]
                self.assertEqual(actual, [actual[0]] * int(multiple))
                expected_preamp = 20.0 * math.log10(self.base.preamp_linear) * multiple
                self.assertIn(f"Preamp: {expected_preamp:.9f} dB", cfg)

    def test_fractional_modes_apply_only_one_reduced_biquad(self):
        for fraction in (0.25, 0.5):
            with self.subTest(intensity=fraction):
                cfg = generate_apo_config(replace(self.base, intensity=fraction), self.library)
                self.assertEqual(cfg.count("ON IIR Order 2"), len(COMMON_SAMPLE_RATES))
                # The fallback (uncommon rates) is consistent with scaled gain.
                self.assertIn(f"Gain {6*fraction:.1f} dB", cfg)
                self.assertIn("Fractional intensity approximates", cfg)
                self.assertIn(f"Preamp: {20*math.log10(0.5)*fraction:.9f} dB", cfg)
                self.assertNotIn("ON IIR Order 4", cfg)

    def test_x2_is_not_single_twelve_db_biquad(self):
        cfg = generate_apo_config(replace(self.base, intensity=2.0), self.library)
        coeff_x1 = _biquad("lowshelf", 60, 6.0, 44100)
        coeff_x12 = _biquad("lowshelf", 60, 12.0, 44100)
        self.assertNotEqual(coeff_x1, coeff_x12)
        rate_block = cfg.split("If: sampleRate == 44100\n", 1)[1].split("ElseIf:", 1)[0]
        self.assertEqual(rate_block.count("ON IIR Order 2"), 2)

    def test_default_backward_compatibility(self):
        s = Settings.from_dict({"enabled": True, "presetId": "CUSTOM",
                               "preampLinear": 1, "gainsDb": [0]*10}, self.library["frequenciesHz"])
        self.assertEqual(s.intensity, 1.0)

    def test_reject_invalid_and_non_preset_multipliers(self):
        data = self.base.to_dict()
        for bad in (-1, 0, 0.1, 1.25, 8, float("nan"), "2", True):
            with self.subTest(bad=bad):
                self.assertRaises(SettingsError, Settings.from_dict, {**data, "intensity":bad}, self.library["frequenciesHz"])

    def test_persistence(self):
        setting = replace(self.base, intensity=4.0)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"settings.json"
            save_settings(setting, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["intensity"], 4.0)
            self.assertEqual(load_settings(self.library,path),setting)

    def test_disabled_remains_bypassed_at_x4(self):
        cfg = generate_apo_config(replace(self.base,enabled=False,intensity=4),self.library)
        self.assertNotIn("Preamp:",cfg)
        self.assertNotIn("ON IIR",cfg)


if __name__ == "__main__":
    unittest.main()
