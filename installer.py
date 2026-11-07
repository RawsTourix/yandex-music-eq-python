"""Download the official Equalizer APO x64 installer and verify its SHA-256."""
from __future__ import annotations
import ctypes
import hashlib
import os
import platform
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

VERSION = "1.4.2"
FILENAME = f"EqualizerAPO-x64-{VERSION}.exe"
OFFICIAL_PAGE = "https://sourceforge.net/projects/equalizerapo/files/"
DOWNLOAD_URL = f"https://downloads.sourceforge.net/project/equalizerapo/{VERSION}/{FILENAME}"
# Fingerprint published on the official SourceForge file download page.
EXPECTED_SHA256 = "7403be7427bbe1936a40dded082829b6e217fc4f5990fee5cba501f0ae055afa"
MAX_BYTES = 64 * 1024 * 1024


class InstallerError(RuntimeError):
    """Safe-to-display error."""


def supported_architecture(machine: str | None = None) -> bool:
    return (machine or platform.machine()).lower() in {"amd64", "x86_64"}


def sha256_matches(path: Path, expected: str | None = None) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest().lower() == (expected or EXPECTED_SHA256).lower()


def download_official_installer(on_progress: Callable[[int], None] | None = None,
                                destination: Path | None = None) -> Path:
    """Use a pinned release and never execute unverified bytes."""
    if not supported_architecture():
        raise InstallerError("Автоматическая установка доступна только для Windows x64.")
    path = destination or Path(tempfile.gettempdir()) / "yandex_music_eq_python" / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if sha256_matches(path):
            if on_progress:
                on_progress(100)
            return path
        path.unlink()
    partial = path.with_name(path.name + ".part")
    partial.unlink(missing_ok=True)
    total = 0
    h = hashlib.sha256()
    try:
        request = urllib.request.Request(DOWNLOAD_URL, headers={
            "User-Agent": "Mozilla/5.0 (YandexMusicEQPython; verified installer)",
            "Accept": "application/octet-stream"})
        with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as output:
            if urlsplit(response.geturl()).scheme != "https":
                raise InstallerError("Загрузка перенаправлена на незащищённый HTTP-адрес.")
            length_header = response.headers.get("Content-Length")
            length = int(length_header) if length_header and length_header.isdecimal() else 0
            if length > MAX_BYTES:
                raise InstallerError("Размер установщика превышает ограничение.")
            while chunk := response.read(65536):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise InstallerError("Установщик превышает ограничение размера.")
                output.write(chunk)
                h.update(chunk)
                if length and on_progress:
                    on_progress(min(99, round(total / length * 100)))
        if not total or h.hexdigest().lower() != EXPECTED_SHA256:
            raise InstallerError("SHA-256 не совпала с официальной! Установщик не запущен.")
        partial.replace(path)
        if on_progress:
            on_progress(100)
        return path
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        raise InstallerError(f"Ошибка загрузки SourceForge: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)


def launch_verified_installer(path: Path) -> None:
    """After explicit user confirmation, request UAC for interactive setup."""
    if os.name != "nt":
        raise InstallerError("Установка доступна только в Windows.")
    if not path.is_file() or not sha256_matches(path):
        raise InstallerError("Установщик не прошёл проверку SHA-256.")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = shell32.ShellExecuteW(None, "runas", str(path), None, str(path.parent), 1)
    if not result or result <= 32:
        if ctypes.get_last_error() == 1223:
            raise InstallerError("Запрос UAC отменён пользователем.")
        raise InstallerError(f"Не удалось запустить установщик (код {result}).")
