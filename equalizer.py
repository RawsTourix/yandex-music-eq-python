"""Validated Yandex Music equalizer settings and Equalizer APO export.

The original Web Audio implementation uses one low shelf, eight peaking filters,
then a high shelf in series. Its preamp is a linear gain factor (not dB).

This module deliberately contains no proprietary frontend JavaScript.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRESETS_FILE = ROOT / "presets.json"
SETTINGS_FILE = ROOT / "settings.json"
COMMON_SAMPLE_RATES = (44100, 48000, 88200, 96000, 176400, 192000)
INTENSITIES = (0.25, 0.5, 1.0, 2.0, 4.0)


class SettingsError(ValueError):
    """Invalid or inconsistent equalizer settings."""


def _number(value: object, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsError(f"{label}: expected a number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise SettingsError(f"{label}: expected {minimum}..{maximum}")
    return number


def _intensity(value: object, label: str) -> float:
    number = _number(value, INTENSITIES[0], INTENSITIES[-1], label)
    if number not in INTENSITIES:
        raise SettingsError(f"{label}: expected one of {INTENSITIES}")
    return number


@dataclass(frozen=True)
class Settings:
    enabled: bool
    preset_id: str
    preamp_linear: float
    gains_db: tuple[float, ...]
    preamp_intensity: float = 1.0
    band_intensities: tuple[float, ...] = (1.0,) * 10

    @classmethod
    def from_dict(cls, data: dict, frequencies: list[int]) -> "Settings":
        if not isinstance(data, dict):
            raise SettingsError("settings must be an object")
        enabled = data.get("enabled", False)
        preset_id = data.get("presetId", "DEFAULT")
        gains = data.get("gainsDb", [0.0] * len(frequencies))
        if not isinstance(enabled, bool) or not isinstance(preset_id, str):
            raise SettingsError("invalid enabled or presetId")
        if not isinstance(gains, list) or len(gains) != len(frequencies):
            raise SettingsError("invalid band count")
        # Migrate the former global intensity into all 11 individual controls.
        # Explicit new fields take precedence; missing fields use the legacy value.
        legacy = data.get("intensity", 1.0)
        preamp_intensity = _intensity(data.get("preampIntensity", legacy), "preamp intensity")
        band_values = data.get("bandIntensities", [legacy] * len(frequencies))
        if not isinstance(band_values, list) or len(band_values) != len(frequencies):
            raise SettingsError("invalid intensity band count")
        band_intensities = tuple(
            _intensity(value, f"band {index + 1} intensity")
            for index, value in enumerate(band_values)
        )
        return cls(enabled, preset_id, _number(data.get("preampLinear", 1.0), .5, 1.5, "preamp"),
                   tuple(_number(g, -12, 12, "band gain") for g in gains),
                   preamp_intensity, band_intensities)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "presetId": self.preset_id,
                "preampLinear": self.preamp_linear, "gainsDb": list(self.gains_db),
                "preampIntensity": self.preamp_intensity,
                "bandIntensities": list(self.band_intensities)}


def load_library(path: Path = PRESETS_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    frequencies = data["frequenciesHz"]
    if frequencies != [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]:
        raise SettingsError("unexpected frequency layout")
    if data["filterTypes"] != ["lowshelf"] + ["peaking"] * 8 + ["highshelf"]:
        raise SettingsError("unexpected filter layout")
    if data.get("q") != 1.0:
        raise SettingsError("unexpected Q")
    for key, preset in data["presets"].items():
        Settings.from_dict({"enabled": True, "presetId": key,
                            "preampLinear": preset["preampLinear"],
                            "gainsDb": preset["gainsDb"]}, frequencies)
    return data


def preset_settings(library: dict, preset_id: str, *, enabled: bool) -> Settings:
    preset = library["presets"][preset_id]
    return Settings.from_dict({"enabled": enabled, "presetId": preset_id,
                               "preampLinear": preset["preampLinear"],
                               "gainsDb": preset["gainsDb"]}, library["frequenciesHz"])


def load_settings(library: dict, path: Path = SETTINGS_FILE,
                  user_preset_ids=()) -> Settings:
    if path.exists():
        result = Settings.from_dict(json.loads(path.read_text(encoding="utf-8")), library["frequenciesHz"])
        if result.preset_id not in library["presets"] and result.preset_id not in user_preset_ids:
            # The selected user preset may have been deleted or moved.
            # Keep the live sound settings; fall back to unsaved Custom.
            if result.preset_id.startswith("USER:"):
                return Settings(result.enabled, "CUSTOM", result.preamp_linear,
                                result.gains_db, result.preamp_intensity, result.band_intensities)
            raise SettingsError(f"unknown preset: {result.preset_id}")
        return result
    return preset_settings(library, "DEFAULT", enabled=False)


def load_custom(library: dict, path: Path = SETTINGS_FILE) -> Settings:
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        custom = saved.get("customPreset")
        if custom is not None:
            return Settings.from_dict({"enabled": False, "presetId": "CUSTOM", **custom}, library["frequenciesHz"])
        if saved.get("presetId") == "CUSTOM":
            current = Settings.from_dict(saved, library["frequenciesHz"])
            return Settings(False, "CUSTOM", current.preamp_linear, current.gains_db)
    return preset_settings(library, "CUSTOM", enabled=False)


def save_settings(settings: Settings, path: Path = SETTINGS_FILE, custom: Settings | None = None) -> None:
    """Persist portable user settings beside the script (no AppData needed)."""
    data = settings.to_dict()
    if custom is not None:
        data["customPreset"] = {"preampLinear": custom.preamp_linear, "gainsDb": list(custom.gains_db)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _biquad(kind: str, hz: int, gain_db: float, sample_rate: int, q: float = 1.0) -> tuple[float, ...]:
    """RBJ/Web Audio biquad coefficients in b0,b1,b2,a0,a1,a2 order.

    Shelf filters use S=1 (Web Audio ignores BiquadFilterNode.Q for shelves).
    Numeric verification against the browser's actual response remains required.
    """
    a = 10 ** (gain_db / 40.0)
    w = 2 * math.pi * hz / sample_rate
    cw, sw = math.cos(w), math.sin(w)
    if kind == "peaking":
        alpha = sw / (2 * q)
        return (1 + alpha * a, -2 * cw, 1 - alpha * a,
                1 + alpha / a, -2 * cw, 1 - alpha / a)
    # Web Audio shelf slope is fixed to S=1, and shelf Q is ignored.
    alpha = sw / math.sqrt(2)
    z = 2 * math.sqrt(a) * alpha
    if kind == "lowshelf":
        return (a * ((a + 1) - (a - 1) * cw + z),
                2 * a * ((a - 1) - (a + 1) * cw),
                a * ((a + 1) - (a - 1) * cw - z),
                (a + 1) + (a - 1) * cw + z,
                -2 * ((a - 1) + (a + 1) * cw),
                (a + 1) + (a - 1) * cw - z)
    if kind == "highshelf":
        return (a * ((a + 1) + (a - 1) * cw + z),
                -2 * a * ((a - 1) + (a + 1) * cw),
                a * ((a + 1) + (a - 1) * cw - z),
                (a + 1) - (a - 1) * cw + z,
                2 * ((a - 1) - (a + 1) * cw),
                (a + 1) - (a - 1) * cw - z)
    raise ValueError(kind)


def generate_apo_config(settings: Settings, library: dict) -> str:
    """Generate an Equalizer APO include file, sample-rate-aware where possible.

    The 11 multipliers are independent: preamp_linear ** preamp_intensity,
    and N copies of an original biquad for bands with integer intensity N.
    Fractional band intensity approximates reduced processing by scaling band
    gain dB; it is not the exact fractional complex transfer-function power.
    Since the linear filters commute, adjacent copies of a band are equivalent
    to serially repeating complete chains for identical multiplier settings.
    No audio is processed by Python; the system APO executes these commands.
    """
    lines = ["# Yandex Music EQ Python - auto-generated; edit using the GUI", "# Do not edit manually"]
    if not settings.enabled:
        return "\n".join(lines + ["# Disabled: no processing commands", ""])

    if len(settings.band_intensities) != len(settings.gains_db):
        raise SettingsError("intensity band count mismatch")
    preamp_factor = _intensity(settings.preamp_intensity, "preamp intensity")
    bands = tuple(zip(
        library["frequenciesHz"], library["filterTypes"],
        settings.gains_db, settings.band_intensities,
    ))
    lines.append(f"# Preamp intensity x{preamp_factor:g}")
    lines.append("# Band intensities: " + ", ".join(
        f"{factor:g}" for factor in settings.band_intensities
    ))
    # Scalar preamp gain is independent of the ten biquad multipliers.
    preamp_db = 20 * math.log10(settings.preamp_linear) * preamp_factor
    lines.append(f"Preamp: {preamp_db:.9f} dB")
    active = []
    for hz, kind, gain, factor in bands:
        factor = _intensity(factor, f"{hz} Hz intensity")
        if abs(gain) <= 1e-10:
            continue
        if factor < 1:
            # Fractional approximation: preserve Q, attenuate dB.
            active.append((hz, kind, gain * factor))
        else:
            # Exact serial copies for x1/x2/x4, not one stronger biquad.
            active.extend([(hz, kind, gain)] * int(factor))
    if not active:
        return "\n".join(lines + [""])
    for i, rate in enumerate(COMMON_SAMPLE_RATES):
        lines.append(f"{'If' if i == 0 else 'ElseIf'}: sampleRate == {rate}")
        for j, (hz, kind, gain) in enumerate(active, 1):
            c = _biquad(kind, hz, gain, rate)
            lines.append("    Filter {}: ON IIR Order 2 Coefficients {}".format(
                j, " ".join(f"{v:.14g}" for v in c)))
    lines.append("Else:")
    lines.append("    # Fallback for uncommon sample rates: native APO filters")
    types = {"lowshelf": "LS", "peaking": "PK", "highshelf": "HS"}
    for j, (hz, kind, gain) in enumerate(active, 1):
        extra = " Q 1.0" if kind == "peaking" else ""
        lines.append(f"    Filter {j}: ON {types[kind]} Fc {hz} Hz Gain {gain:.6g} dB{extra}")
    lines.extend(["EndIf:", ""])
    return "\n".join(lines)
