"""Screenshots and screen recording."""
from __future__ import annotations

import time

from .adb import Adb

_REMOTE_DIR = "/sdcard"


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def screenshot(adb: Adb, serial: str, dest_path: str) -> str:
    remote = f"{_REMOTE_DIR}/adbmanager-{timestamp()}.png"
    try:
        adb.shell(serial, f"screencap -p {remote}")
        adb.run_device(serial, ["pull", remote, dest_path], timeout=120)
    finally:
        adb.shell(serial, f"rm -f {remote}", check=False)
    return dest_path


def record(adb: Adb, serial: str, dest_path: str, seconds: int = 30) -> str:
    """Record the screen for `seconds` (Android caps it at 180) and pull the file."""
    seconds = max(1, min(int(seconds), 180))
    remote = f"{_REMOTE_DIR}/adbmanager-{timestamp()}.mp4"
    try:
        adb.shell(serial, f"screenrecord --time-limit {seconds} {remote}",
                  timeout=seconds + 30)
        time.sleep(1)  # let the encoder finalize the file
        adb.run_device(serial, ["pull", remote, dest_path], timeout=None)
    finally:
        adb.shell(serial, f"rm -f {remote}", check=False)
    return dest_path
