"""Safe, narrowly scoped Equalizer APO integration.

One-time setup is done by setup_apo.py with elevation. Runtime edits affect
only yandex-music-eq.txt; other APO settings are never overwritten by the GUI.
"""

from __future__ import annotations

import os
from pathlib import Path

from equalizer import Settings, generate_apo_config

MANAGED_NAME = "yandex-music-eq.txt"
INCLUDE_DIRECTIVE = f"Include: {MANAGED_NAME}"


def config_directory() -> Path | None:
    if os.name != "nt":
        return None
    # Standard path. The configurable installation directory is also stored
    # in the registry by Equalizer APO on most installations.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO") as key:
            root, _ = winreg.QueryValueEx(key, "ConfigPath")
            if isinstance(root, str) and Path(root).is_dir():
                return Path(root)
    except (OSError, ImportError):
        pass
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for root in filter(None, roots):
        candidate = Path(root) / "EqualizerAPO" / "config"
        if candidate.is_dir():
            return candidate
    return None


def managed_file() -> Path | None:
    directory = config_directory()
    return (directory / MANAGED_NAME) if directory else None


def is_connected() -> bool:
    directory = config_directory()
    if directory is None or not (directory / MANAGED_NAME).is_file():
        return False
    main = directory / "config.txt"
    if not main.is_file():
        return False
    text = main.read_text(encoding="utf-8-sig", errors="replace")
    return any(line.strip().lower() == INCLUDE_DIRECTIVE.lower() for line in text.splitlines())


def apply(settings: Settings, library: dict) -> bool:
    """Update the installed, pre-authorized file, or return False if not set up.

    Overwrite in place: the setup helper grants permission on this FILE only,
    not the privileged directory. The file is watched by Equalizer APO.
    """
    if not is_connected():
        return False
    target = managed_file()
    assert target is not None
    target.write_text(generate_apo_config(settings, library), encoding="utf-8")
    return True
