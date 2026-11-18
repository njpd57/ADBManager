"""Shell commands, logcat arguments/filtering and reboot modes."""
from __future__ import annotations

from .adb import Adb

LOG_LEVELS = ["V", "D", "I", "W", "E", "F"]
REBOOT_MODES = {
    "Normal": [],
    "Recovery": ["recovery"],
    "Bootloader": ["bootloader"],
    "Fastbootd": ["fastboot"],
    "Sideload": ["sideload"],
}


def logcat_args(level: str = "V", tag: str = "") -> list[str]:
    """Build `logcat` arguments. With a tag, only that tag is shown at `level` or above."""
    filters = [f"{tag}:{level}", "*:S"] if tag else [f"*:{level}"]
    return ["logcat", "-v", "threadtime", *filters]


def line_matches(line: str, text: str, case_sensitive: bool = False) -> bool:
    if not text:
        return True
    return text in line if case_sensitive else text.lower() in line.lower()


def run_shell(adb: Adb, serial: str, command: str) -> str:
    _, out, err = adb.shell(serial, command, timeout=120, check=False)
    return (out + ("\n" + err if err else "")).rstrip()


def clear_logcat(adb: Adb, serial: str) -> None:
    adb.run_device(serial, ["logcat", "-c"], timeout=15)


def reboot(adb: Adb, serial: str, mode: str) -> None:
    adb.run_device(serial, ["reboot", *REBOOT_MODES[mode]], timeout=30)
