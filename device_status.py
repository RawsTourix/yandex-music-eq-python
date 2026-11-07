"""Read-only checks of Equalizer APO registration on Windows playback endpoints.

A registry entry is not proof that the audio engine has loaded or is processing
with that APO; use the device selector's test for final confirmation.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}")
RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"


@dataclass(frozen=True)
class DeviceStatus:
    state: str             # registered, missing, unknown
    device_name: str
    reason: str


def endpoint_guid(device_id: str) -> str | None:
    """Extract the endpoint GUID from a WASAPI/Qt device ID, if recognizable."""
    matches = GUID.findall(device_id or "")
    return matches[-1].lower() if matches else None


def classify_device(default_id: str, default_name: str, post_mix_guids: set[str] | None) -> DeviceStatus:
    """Conservative interpretation of per-endpoint *post-mix* registry evidence."""
    name = default_name or "устройство по умолчанию"
    if post_mix_guids is None:
        return DeviceStatus("unknown", name, "Не удалось проверить регистрацию APO в реестре Windows")
    guid = endpoint_guid(default_id)
    if guid is not None:
        if guid in {g.lower() for g in post_mix_guids}:
            return DeviceStatus("registered", name, f"Equalizer APO зарегистрирован для «{name}». Реальная обработка звука не проверена")
        return DeviceStatus("missing", name, f"Equalizer APO не зарегистрирован на post-mix для «{name}». Выберите устройство в Device Selector")
    if not post_mix_guids:
        return DeviceStatus("missing", name, "Не найдено ни одного устройства вывода с зарегистрированным post-mix Equalizer APO")
    return DeviceStatus("unknown", name, f"APO найден на других устройствах, но идентификатор «{name}» не удалось сопоставить; проверьте Device Selector")


def _is_equalizer_post_mix(clsid: str, winreg) -> bool:
    # Names are assigned by Equalizer APO's DllRegisterServer. We do not
    # assume any arbitrary COM GUID belongs to Equalizer APO.
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid,
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            title, _ = winreg.QueryValueEx(key, "")
            return isinstance(title, str) and title.casefold().startswith("equalizerapo post-mix")
    except OSError:
        return False


def registered_post_mix_endpoints() -> set[str] | None:
    """Read-only detection matching Equalizer APO's DeviceAPOInfo approach."""
    if os.name != "nt":
        return None
    try:
        import winreg
        results: set[str] = set()
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER_KEY,
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, i)
                endpoint = endpoint_guid(name)
                if not endpoint:
                    continue
                try:
                    with winreg.OpenKey(root, name + r"\FxProperties") as fx:
                        for j in range(winreg.QueryInfoKey(fx)[1]):
                            _, value, _ = winreg.EnumValue(fx, j)
                            if isinstance(value, str):
                                clsid = endpoint_guid(value)
                                if clsid and _is_equalizer_post_mix(clsid, winreg):
                                    results.add(endpoint)
                                    break
                except FileNotFoundError:
                    pass
        return results
    except (OSError, ImportError):
        return None


def inspect_default_output() -> DeviceStatus:
    if os.name != "nt":
        return DeviceStatus("unknown", "", "Проверка устройств доступна только в Windows")
    try:
        from PySide6.QtMultimedia import QMediaDevices
        audio = QMediaDevices.defaultAudioOutput()
        if audio.isNull():
            return DeviceStatus("unknown", "", "Windows не сообщает об устройстве вывода по умолчанию")
        name = audio.description()
        device_id = bytes(audio.id()).decode("utf-8", "replace")
    except (ImportError, OSError, RuntimeError) as exc:
        return DeviceStatus("unknown", "", f"Не удалось определить текущий аудиовыход: {exc}")
    return classify_device(device_id, name, registered_post_mix_endpoints())
