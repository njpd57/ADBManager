"""Backup/restore, runtime permissions, sideload and basic fastboot."""
from __future__ import annotations

import re
import shlex

from .adb import Adb, AdbError, find_fastboot


def backup(adb: Adb, serial: str, dest_file: str, package: str | None = None,
           include_apk: bool = True, include_shared: bool = False) -> str:
    """Run `adb backup`. The user must confirm on the device screen."""
    args = ["backup", "-f", dest_file]
    args.append("-apk" if include_apk else "-noapk")
    args.append("-shared" if include_shared else "-noshared")
    args.append(package if package else "-all")
    _, out, err = adb.run_device(serial, args, timeout=None)
    return (out + err).strip() or "Backup finished"


def restore(adb: Adb, serial: str, backup_file: str) -> str:
    _, out, err = adb.run_device(serial, ["restore", backup_file], timeout=None)
    return (out + err).strip() or "Restore finished"


def sideload(adb: Adb, serial: str, zip_file: str) -> str:
    _, out, err = adb.run_device(serial, ["sideload", zip_file], timeout=None)
    return (out + err).strip() or "Sideload finished"


def parse_permissions(dumpsys_output: str) -> dict[str, bool]:
    """Parse runtime permissions of `dumpsys package <pkg>` -> {permission: granted}."""
    permissions: dict[str, bool] = {}
    for match in re.finditer(r"^\s+([\w.]+(?:permission|PERMISSION)[\w.]*): granted=(true|false)",
                             dumpsys_output, re.M):
        permissions[match.group(1)] = match.group(2) == "true"
    return permissions


def list_permissions(adb: Adb, serial: str, package: str) -> dict[str, bool]:
    _, out, _ = adb.shell(serial, f"dumpsys package {shlex.quote(package)}", timeout=30)
    return parse_permissions(out)


def set_permission(adb: Adb, serial: str, package: str, permission: str, grant: bool) -> None:
    verb = "grant" if grant else "revoke"
    _, out, err = adb.shell(serial, f"pm {verb} {shlex.quote(package)} {shlex.quote(permission)}",
                            check=False)
    text = (out + err).strip()
    if text:
        raise AdbError(text)


def fastboot(adb: Adb, args: list[str]) -> str:
    """Run a fastboot command (device must already be in bootloader mode)."""
    _, out, err = adb.run(args, timeout=60, check=False, binary=find_fastboot())
    return (out + "\n" + err).strip()
