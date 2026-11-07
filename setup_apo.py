"""One-time Equalizer APO integration with a visible, reportable UAC result.

The GUI starts this helper as a normal subprocess. It elevates only the
one-time installation phase and reports its success/failure back to the GUI.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from apo import INCLUDE_DIRECTIVE, MANAGED_NAME, config_directory
from equalizer import generate_apo_config, load_library, load_settings


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def current_sid() -> str:
    raw = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
    rows = list(csv.reader(raw.splitlines()))
    if not rows or len(rows[0]) < 2 or not re.fullmatch(r"S-1-(?:\d+-)+\d+", rows[0][1]):
        raise RuntimeError("Не удалось определить SID текущего пользователя Windows")
    return rows[0][1]


def elevated() -> bool:
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def request_elevation_and_wait(sid: str, report: Path) -> int:
    """Launch the narrow setup step with runas; wait without blocking GUI.

    This function executes in a separate QProcess, not in the Qt UI thread.
    """
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    params = subprocess.list2cmdline([
        str(Path(__file__).resolve()), "--elevated", "--sid", sid,
        "--report", str(report),
    ])
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = sys.executable
    info.lpParameters = params
    info.lpDirectory = str(Path(__file__).resolve().parent)
    info.nShow = 0  # no console flash for the elevated helper

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise RuntimeError("Запрос прав администратора отменён пользователем (UAC)")
        raise OSError(code, f"Не удалось запросить права администратора (код Windows {code})")
    if not info.hProcess:
        raise RuntimeError("Windows не вернула дескриптор процесса настройки APO")
    try:
        wait = kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        if wait != 0:  # WAIT_OBJECT_0
            raise RuntimeError(f"Не удалось дождаться настройки APO (код {wait})")
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


def install(sid: str) -> str:
    directory = config_directory()
    if directory is None:
        raise RuntimeError("Equalizer APO не найден. Сначала установите его и настройте Configurator")
    config = directory / "config.txt"
    target = directory / MANAGED_NAME
    if not target.exists():
        library = load_library()
        target.write_text(generate_apo_config(load_settings(library), library), encoding="utf-8")

    acl = subprocess.run(["icacls", str(target), "/grant", f"*{sid}:(M)"], capture_output=True, text=True)
    if acl.returncode != 0:
        raise RuntimeError(f"Не удалось выдать доступ на запись {target}: {acl.stderr or acl.stdout}")

    previous = config.read_bytes() if config.exists() else b""
    lines = previous.decode("utf-8-sig", errors="replace").splitlines()
    if not any(line.strip().lower() == INCLUDE_DIRECTIVE.lower() for line in lines):
        if config.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = directory / f"config.txt.before-yandex-eq-{stamp}.bak"
            backup.write_bytes(previous)
        suffix = b"" if not previous or previous.endswith((b"\r", b"\n")) else b"\r\n"
        addition = ("# Yandex Music EQ Python (managed)\r\n"
                    "Device: all\r\nStage: post-mix\r\nChannel: all\r\n"
                    + INCLUDE_DIRECTIVE + "\r\n")
        config.write_bytes(previous + suffix + addition.encode("ascii"))
    return f"Конфигурация подключена: {target}. Проверьте, что APO включён в Configurator для вашего устройства вывода"


def _emit_result(report: Path | None, ok: bool, message: str) -> None:
    payload = json.dumps({"ok": ok, "message": message}, ensure_ascii=False)
    if report is None:
        # Avoid OEM/ANSI codepage corruption when Qt captures stdout on Windows.
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    else:
        report.write_text(payload + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elevated", action="store_true")
    parser.add_argument("--sid", default="")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if os.name != "nt":
        _emit_result(args.report if args.elevated else None, False, "Обработка системного звука поддерживается только в Windows")
        return 1

    if args.elevated:
        try:
            if not elevated() or not re.fullmatch(r"S-1-(?:\d+-)+\d+", args.sid):
                raise RuntimeError("Для установки необходимы права администратора и SID пользователя")
            message = install(args.sid)
            _emit_result(args.report, True, message)
            return 0
        except (OSError, RuntimeError, ValueError) as exc:
            _emit_result(args.report, False, f"Ошибка настройки APO: {exc}")
            return 1

    # Non-elevated wrapper: all messages are visible to Qt through QProcess stdout.
    if config_directory() is None:
        _emit_result(None, False, "Equalizer APO не установлен или не найден. Установите Equalizer APO и выберите устройство в Configurator")
        return 1
    try:
        sid = current_sid()
        with tempfile.TemporaryDirectory(prefix="yandex_eq_") as temp:
            report = Path(temp) / "result.json"
            code = request_elevation_and_wait(sid, report)
            if not report.is_file():
                raise RuntimeError(f"Установщик завершился с кодом {code}, но не вернул отчёт")
            payload = json.loads(report.read_text(encoding="utf-8"))
            _emit_result(None, bool(payload.get("ok")) and code == 0, str(payload.get("message", "Нет отчёта")))
            return 0 if payload.get("ok") and code == 0 else 1
    except (OSError, RuntimeError, ValueError) as exc:
        _emit_result(None, False, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())