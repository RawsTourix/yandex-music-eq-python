"""Explicit application shutdown: disable EQ in APO before process exit.

The audio processor lives in the Windows audio service, not inside the GUI.
Stopping the Python process alone never guarantees the filters are removed.
"""
from __future__ import annotations

from dataclasses import replace

import apo
from equalizer import Settings, save_settings


class ShutdownError(RuntimeError):
    """Could not safely turn off the last active Equalizer APO configuration."""


def disable_and_persist(
    settings: Settings,
    custom: Settings,
    library: dict,
    *,
    is_connected=None,
    apply=None,
    save=None,
) -> Settings:
    """Persist disabled DSP and retain sliders/presets for the next launch.

    If Equalizer APO is connected, it MUST accept a disabled config before
    shutdown succeeds. Fail closed: the caller must not quit on any failure.
    Dependency injection is deliberately limited to make failure tests exact.
    """
    is_connected = is_connected or apo.is_connected
    apply = apply or apo.apply
    save = save or save_settings

    disabled = replace(settings, enabled=False)
    try:
        if is_connected() and not apply(disabled, library):
            raise ShutdownError("Не удалось записать выключенную конфигурацию Equalizer APO")
        save(disabled, custom=custom)
    except (OSError, ValueError) as exc:
        raise ShutdownError(f"Не удалось отключить эквалайзер: {exc}") from exc
    return disabled
