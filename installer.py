"""Verified, opt-in download of Equalizer APO x64 from SourceForge mirrors.

The checksum is pinned to the vendor's official release page. Neither a web
page nor an EXE with a mismatched digest can be launched by this module.
"""
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
# SourceForge publishes these mirror hosts. These are alternatives, NOT a bypass
# of the cryptographic verification, which applies to every candidate.
DOWNLOAD_URLS = (
    DOWNLOAD_URL,
    f"https://netix.dl.sourceforge.net/project/equalizerapo/{VERSION}/{FILENAME}",
    f"https://psychz.dl.sourceforge.net/project/equalizerapo/{VERSION}/{FILENAME}",
)
# From https://sourceforge.net/projects/equalizerapo/files/1.4.2/EqualizerAPO-x64-1.4.2.exe/download
EXPECTED_SHA256 = "7403be7427bbe1936a40dded082829b6e217fc4f5990fee5cba501f0ae055afa"
MAX_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class InstallerError(RuntimeError):
    """Safe-to-display diagnostic for a failed installer download or launch."""


def supported_architecture(machine: str | None = None) -> bool:
    return (machine or platform.machine()).lower() in {"amd64", "x86_64"}


def sha256_matches(path: Path, expected: str | None = None) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == (expected or EXPECTED_SHA256).lower()


def _download_one(url: str, partial: Path, on_progress: Callable[[int], None] | None) -> None:
    """Fetch one candidate to a temporary path and accept only pinned SHA-256."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "YandexMusicEQPython/0.1 (SourceForge file downloader)",
        "Accept": "application/octet-stream",
    })
    with urllib.request.urlopen(request, timeout=45) as response:
        redirected = urlsplit(response.geturl())
        if redirected.scheme.lower() != "https":
            raise InstallerError("SourceForge перенаправил загрузку на HTTP (не HTTPS).")
        host = redirected.hostname or "неизвестный хост"
        mime = response.headers.get("Content-Type", "не указан")
        declared = response.headers.get("Content-Length", "")
        length = int(declared) if declared.isdecimal() else 0
        if length > MAX_BYTES:
            raise InstallerError("Сервер сообщил слишком большой размер установщика.")
        digest = hashlib.sha256()
        total = 0
        with partial.open("wb") as output:
            while chunk := response.read(CHUNK_BYTES):
                if total == 0 and not chunk.startswith(b"MZ"):
                    if "html" in mime.lower() or chunk.lstrip().lower().startswith((b"<!doctype", b"<html", b"<head")):
                        raise InstallerError(f"Вместо EXE получена HTML-страница от {host} (тип {mime}).")
                    raise InstallerError(f"Сервер {host} вернул данные без заголовка EXE (MZ), тип {mime}.")
                total += len(chunk)
                if total > MAX_BYTES:
                    raise InstallerError("Файл превысил максимальный размер 64 МиБ.")
                output.write(chunk)
                digest.update(chunk)
                if length and on_progress:
                    on_progress(min(99, round(total * 100 / length)))
        actual = digest.hexdigest().lower()
        if not total:
            raise InstallerError(f"Сервер {host} вернул пустой файл.")
        if actual != EXPECTED_SHA256.lower():
            raise InstallerError(
                f"SHA-256 не совпадает: от {host} получено {total} байт, "
                f"SHA-256={actual}. Ожидается {EXPECTED_SHA256}. Файл НЕ запущен."
            )


def download_official_installer(on_progress: Callable[[int], None] | None = None,
                                destination: Path | None = None) -> Path:
    """Try official mirrors, never keeping or running unverifiable downloads."""
    if not supported_architecture():
        raise InstallerError("Автоустановка доступна только на Windows x64.")
    path = destination or Path(tempfile.gettempdir()) / "yandex_music_eq_python" / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256_matches(path):
            if on_progress:
                on_progress(100)
            return path
        path.unlink()
    partial = path.with_name(path.name + ".part")
    errors = []
    for index, url in enumerate(DOWNLOAD_URLS, 1):
        partial.unlink(missing_ok=True)
        if on_progress:
            on_progress(0)
        try:
            _download_one(url, partial, on_progress)
            partial.replace(path)
            if on_progress:
                on_progress(100)
            return path
        except (InstallerError, urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            # Bad bytes are discarded before trying the next *official* mirror.
            errors.append(f"{index}. {urlsplit(url).hostname}: {exc}")
        finally:
            partial.unlink(missing_ok=True)
    raise InstallerError(
        "Ни одно из зеркал SourceForge не вернуло файл с официальной SHA-256. "
        "Установщик не запущен. Подробности:\n" + "\n".join(errors) +
        "\nЕсли зеркала недоступны из вашей сети, скачайте EXE вручную на SourceForge."
    )


def launch_verified_installer(path: Path) -> None:
    """Launch only checksum-verified bytes via Windows UAC, never silently."""
    if os.name != "nt":
        raise InstallerError("Установка доступна только в Windows.")
    if not path.is_file() or not sha256_matches(path):
        raise InstallerError("Установщик не прошёл проверку SHA-256; запуск заблокирован.")
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