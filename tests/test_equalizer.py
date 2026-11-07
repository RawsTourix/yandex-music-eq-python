"""Tests run without PySide6 or a Windows machine."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from equalizer import (
    COMMON_SAMPLE_RATES, Settings, SettingsError, _biquad,
    generate_apo_config, load_custom, load_library, load_settings,
    preset_settings, save_settings,
)


def response_db(coefficients, frequency, sample_rate):
    b0, b1, b2, a0, a1, a2 = coefficients
    z = complex(math.cos(-2 * math.pi * frequency / sample_rate),
                math.sin(-2 * math.pi * frequency / sample_rate))
    h = (b0 + b1 * z + b2 * z * z) / (a0 + a1 * z + a2 * z * z)
    return 20 * math.log10(abs(h))


class EqualizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = load_library()

    def test_presets_from_original_bundle(self):
        self.assertEqual(len(self.library["presets"]), 19)
        self.assertEqual(self.library["frequenciesHz"],
                         [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000])
        for name in self.library["presets"]:
            preset = preset_settings(self.library, name, enabled=True)
            self.assertEqual(len(preset.gains_db), 10)
            self.assertTrue(.5 <= preset.preamp_linear <= 1.5)

    def test_sample_rates_and_iir_branching(self):
        settings = Settings(True, "CUSTOM", .6, (8.9, -6.5, -8.5, -9.7, -10.3, -9.5, -8.8, -8.1, -7.6, -7.5))
        text = generate_apo_config(settings, self.library)
        for sample_rate in COMMON_SAMPLE_RATES:
            self.assertIn(f"sampleRate == {sample_rate}", text)
        self.assertEqual(text.count("ON IIR Order 2"), 60)
        self.assertIn("Filter 1: ON LS Fc 60 Hz Gain 8.9 dB", text)
        self.assertIn("Filter 10: ON HS Fc 16000 Hz Gain -7.5 dB", text)
        self.assertIn("Preamp: -4.436974992 dB", text)

    def test_disabled_emits_no_dsp(self):
        settings = preset_settings(self.library, "TECHNO", enabled=False)
        text = generate_apo_config(settings, self.library)
        self.assertNotIn("Preamp:", text)
        self.assertNotIn("Filter ", text)

    def test_unity_filters_can_be_omitted(self):
        settings = preset_settings(self.library, "DEFAULT", enabled=True)
        text = generate_apo_config(settings, self.library)
        self.assertIn("Preamp: 0.000000000 dB", text)
        self.assertNotIn("Filter ", text)

    def test_peaking_center_gain(self):
        b = _biquad("peaking", 1000, 6.0, 48000)
        self.assertAlmostEqual(response_db(b, 1000, 48000), 6.0, places=5)

    def test_shelf_limits(self):
        low = _biquad("lowshelf", 60, 6.0, 48000)
        self.assertAlmostEqual(response_db(low, 0, 48000), 6.0, places=4)
        self.assertAlmostEqual(response_db(low, 24000, 48000), 0.0, places=4)
        high = _biquad("highshelf", 16000, -6.0, 48000)
        self.assertAlmostEqual(response_db(high, 24000, 48000), -6.0, places=4)
        self.assertAlmostEqual(response_db(high, 0, 48000), 0.0, places=4)

    def test_invalid_settings_rejected(self):
        good = {"enabled": True, "presetId": "CUSTOM", "preampLinear": 1.0, "gainsDb": [0] * 10}
        for bad in (float("nan"), 99, True):
            with self.subTest(bad=bad):
                self.assertRaises(SettingsError, Settings.from_dict, {**good, "gainsDb": [bad] + [0] * 9}, self.library["frequenciesHz"])

    def test_portable_settings_and_custom(self):
        settings = Settings(True, "TECHNO", 1.0, tuple([1.0] * 10))
        custom = Settings(False, "CUSTOM", .6, tuple([8.9] * 10))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            save_settings(settings, path, custom)
            self.assertEqual(load_settings(self.library, path), settings)
            self.assertEqual(load_custom(self.library, path), custom)
            self.assertIn("customPreset", json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
