"""Portable user-created EQ presets, separate from the built-in preset library.

The local collection stays out of Git. A single portable JSON preset can be
exported/imported without requiring Equalizer APO or a Windows installation.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from equalizer import ROOT, Settings

USER_PRESETS_FILE = ROOT / "user_presets.json"
FORMAT = "yandex-music-eq-preset"
VERSION = 1
MAX_PRESETS = 200
MAX_FILE_SIZE = 1024 * 1024
MAX_SINGLE_SIZE = 64 * 1024
USER_ID = re.compile(r"USER:[0-9a-f]{32}\Z")
FREQUENCIES = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000]


class UserPresetError(ValueError):
    """A local preset is invalid, duplicated, or cannot be safely imported."""


def normalized_name(value: str) -> str:
    if not isinstance(value, str):
        raise UserPresetError("Название пресета должно быть строкой")
    name = value.strip()
    if not 1 <= len(name) <= 64 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise UserPresetError("Название: от 1 до 64 символов без управляющих символов")
    return name


def snapshot(settings: Settings, name: str) -> dict:
    """Preserve the ten gains, linear preamp, and all eleven intensities."""
    name = normalized_name(name)
    return {
        "name": name,
        "preampLinear": settings.preamp_linear,
        "gainsDb": list(settings.gains_db),
        "preampIntensity": settings.preamp_intensity,
        "bandIntensities": list(settings.band_intensities),
    }


def validate_preset(data: object, frequencies: list[int] = FREQUENCIES) -> dict:
    if not isinstance(data, dict):
        raise UserPresetError("Ожидался объект с параметрами эквалайзера")
    expected = {"name", "preampLinear", "gainsDb", "preampIntensity", "bandIntensities"}
    if set(data) != expected:
        raise UserPresetError("Пресет содержит отсутствующие или неизвестные поля")
    name = normalized_name(data["name"])
    try:
        settings = Settings.from_dict(
            {"enabled": True, "presetId": "CUSTOM",
             "preampLinear": data["preampLinear"], "gainsDb": data["gainsDb"],
             "preampIntensity": data["preampIntensity"],
             "bandIntensities": data["bandIntensities"]}, frequencies
        )
    except (TypeError, ValueError) as exc:
        raise UserPresetError(f"Недопустимые параметры пресета: {exc}") from exc
    return snapshot(settings, name)


def _validate_collection(raw: object, frequencies: list[int]) -> dict[str, dict]:
    if not isinstance(raw, dict) or set(raw) != {"version", "presets"} or raw["version"] != VERSION:
        raise UserPresetError("Неизвестный формат коллекции пользовательских пресетов")
    items = raw["presets"]
    if not isinstance(items, list) or len(items) > MAX_PRESETS:
        raise UserPresetError("Список пресетов некорректен или слишком велик")
    result: dict[str, dict] = {}
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            raise UserPresetError("Пресет не содержит идентификатор")
        preset_id = item["id"]
        if not isinstance(preset_id, str) or not USER_ID.fullmatch(preset_id) or preset_id in result:
            raise UserPresetError("Некорректный либо повторяющийся ID пресета")
        preset = validate_preset({k: v for k, v in item.items() if k != "id"}, frequencies)
        folded = preset["name"].casefold()
        if folded in names:
            raise UserPresetError("Названия пользовательских пресетов должны быть уникальными")
        names.add(folded)
        result[preset_id] = preset
    return result


def load_user_presets(
    path: Path = USER_PRESETS_FILE, frequencies: list[int] = FREQUENCIES
) -> dict[str, dict]:
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_FILE_SIZE:
        raise UserPresetError("Файл пользовательских пресетов слишком велик")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UserPresetError(f"Некорректный JSON пользовательских пресетов: {exc}") from exc
    return _validate_collection(raw, frequencies)


def _write_json_atomic(path: Path, data: dict) -> None:
    """Never replace a valid collection with a partially written JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", suffix=".tmp",
            prefix=".eq-preset-", dir=path.parent, delete=False
        ) as stream:
            staging = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def save_user_presets(
    presets: dict[str, dict], path: Path = USER_PRESETS_FILE,
    frequencies: list[int] = FREQUENCIES,
) -> None:
    serialized = {"version": VERSION, "presets": [
        {"id": preset_id, **record} for preset_id, record in presets.items()
    ]}
    canonical = _validate_collection(serialized, frequencies)
    _write_json_atomic(path, {"version": VERSION, "presets": [
        {"id": preset_id, **record} for preset_id, record in canonical.items()
    ]})


def ensure_unique_name(presets: dict[str, dict], name: str, ignore_id: str | None = None) -> str:
    name = normalized_name(name)
    if any(
        preset_id != ignore_id and preset["name"].casefold() == name.casefold()
        for preset_id, preset in presets.items()
    ):
        raise UserPresetError("Пресет с таким названием уже существует")
    return name


def new_preset_id() -> str:
    return "USER:" + uuid.uuid4().hex


def preset_settings(record: dict, preset_id: str, enabled: bool) -> Settings:
    return Settings.from_dict(
        {"enabled": enabled, "presetId": preset_id, **validate_preset(record)}, FREQUENCIES
    )


def export_preset(record: dict, path: Path) -> None:
    data = validate_preset(record)
    # One preset per file. No platform-specific paths or vendor dependencies.
    _write_json_atomic(path, {"format": FORMAT, "version": VERSION, "preset": data})


def import_preset(path: Path) -> dict:
    if path.stat().st_size > MAX_SINGLE_SIZE:
        raise UserPresetError("Файл импорта слишком велик")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UserPresetError(f"Некорректный JSON при импорте: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"format", "version", "preset"}:
        raise UserPresetError("Файл не является экспортированным пресетом эквалайзера")
    if raw["format"] != FORMAT or raw["version"] != VERSION:
        raise UserPresetError("Неподдерживаемая версия формата экспорта")
    return validate_preset(raw["preset"])
