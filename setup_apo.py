"""One-time Equalizer APO setup for Windows, with explicit UAC consent.

Never deletes or rewrites unrelated APO settings. Creates one managed include,
backing up config.txt before changing it, and grants a normal user access to
that one generated text file rather than to the whole Program Files directory.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import datetime
import os
import subprocess
import sys
from pathlib import Path

from apo import INCLUDE_DIRECTIVE, MANAGED_NAME, config_directory
from equalizer import generate_apo_config, load_library, load_settings


def current_sid() -> str:
    raw = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
    rows = list(csv.reader(raw.splitlines()))
    if not rows or len(rows[0]) < 2 or not rows[0][1].startswith("S-1-"):
        raise RuntimeError("Cannot determine Windows user SID")
    return rows[0][1]


def elevated() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def request_elevation(sid: str) -> bool:
    # The original user SID is explicitly carried into the elevated process.
    args = subprocess.list2cmdline([str(Path(__file__).resolve()), "--elevated", "--sid", sid])
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    return result > 32


def install(sid: str) -> None:
    directory = config_directory()
    if directory is None:
        raise RuntimeError("Equalizer APO installation/config directory not found")
    config = directory / "config.txt"
    target = directory / MANAGED_NAME
    if not target.exists():
        library = load_library()
        settings = load_settings(library)
        target.write_text(generate_apo_config(settings, library), encoding="utf-8")
    acl = subprocess.run(["icacls", str(target), "/grant", f"*{sid}:(M)"], capture_output=True, text=True)
    if acl.returncode != 0:
        raise RuntimeError(f"Cannot grant write permission to {target}: {acl.stderr or acl.stdout}")

    previous = config.read_bytes() if config.exists() else b""
    lines = previous.decode("utf-8-sig", errors="replace").splitlines()
    if not any(line.strip().lower() == INCLUDE_DIRECTIVE.lower() for line in lines):
        if config.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = directory / f"config.txt.before-yandex-eq-{stamp}.bak"
            backup.write_bytes(previous)
            print("Backup:", backup)
        suffix = b"" if not previous else (b"" if previous.endswith((b"\r", b"\n")) else b"\r\n")
        # Appends to preserve the file byte-for-byte otherwise (including BOM).
        config.write_bytes(previous + suffix + ("# Yandex Music EQ Python (managed)\r\nDevice: all\r\nStage: post-mix\r\nChannel: all\r\n" + INCLUDE_DIRECTIVE + "\r\n").encode("ascii"))
    print("Equalizer APO is connected. Managed file:", target)
    print("Note: existing APO filters may stack with this EQ; disable them for an exact comparison.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elevated", action="store_true")
    parser.add_argument("--sid", default="")
    args = parser.parse_args()
    if os.name != "nt":
        print("Equalizer APO integration requires Windows.")
        return 1
    if not elevated():
        sid = current_sid()
        if not request_elevation(sid):
            print("Administrator permission was not granted.")
            return 1
        return 0
    if not args.sid:
        print("Run setup_apo.py without --elevated to pass the original user SID safely.")
        return 1
    try:
        install(args.sid)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print("Setup failed:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
