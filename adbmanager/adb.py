"""Core adb layer: binary discovery, command runner, command log and device listing.

No GUI dependencies. Every executed command is reported to the registered listeners
so the UI can show a command log.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(Exception):
    pass


@dataclass
class Device:
    serial: str
    state: str
    info: str = ""

    @property
    def label(self) -> str:
        model = re.search(r"model:(\S+)", self.info)
        name = model.group(1) if model else ""
        text = f"{name} ({self.serial})" if name else self.serial
        return text if self.state == "device" else f"{text} [{self.state}]"


def _find_binary(name: str, env_var: str, extra: tuple[str, ...]) -> str:
    env = os.environ.get(env_var)
    if env and os.path.isfile(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    for candidate in extra:
        if os.path.isfile(candidate):
            return candidate
    raise AdbError(f"{name} not found. Install platform-tools or set {env_var}.")


def find_adb() -> str:
    return _find_binary("adb", "ADB_PATH", (
        r"C:\platform-tools\adb.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    ))


def find_fastboot() -> str:
    return _find_binary("fastboot", "FASTBOOT_PATH", (
        r"C:\platform-tools\fastboot.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\fastboot.exe"),
    ))


def parse_devices(output: str) -> list[Device]:
    """Parse the output of `adb devices -l`."""
    devices = []
    for line in output.splitlines()[1:]:
        if not line.strip() or line.startswith("*"):
            continue
        parts = line.split(None, 2)
        if len(parts) >= 2:
            devices.append(Device(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return devices


def format_command(binary: str, args: list[str]) -> str:
    name = os.path.splitext(os.path.basename(binary))[0]
    return " ".join([name, *(shlex.quote(a) for a in args)])


class Adb:
    def __init__(self, adb_path: str | None = None):
        self.adb = adb_path or find_adb()
        self._listeners: list[Callable[[str], None]] = []

    # ---- command log ----
    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _emit(self, line: str) -> None:
        for callback in self._listeners:
            callback(line)

    # ---- runners ----
    def run(self, args: list[str], timeout: int | None = 60, check: bool = True,
            binary: str | None = None) -> tuple[int, str, str]:
        exe = binary or self.adb
        self._emit(format_command(exe, args))
        try:
            proc = subprocess.run([exe, *args], capture_output=True, timeout=timeout,
                                  creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise AdbError("The command timed out.")
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace").strip()
        if check and proc.returncode != 0:
            raise AdbError(err or out.strip() or f"Command failed (exit code {proc.returncode})")
        return proc.returncode, out, err

    def run_bytes(self, args: list[str], timeout: int | None = 120) -> bytes:
        """Run a command and return raw stdout bytes (for binary data such as `exec-out`)."""
        self._emit(format_command(self.adb, args))
        try:
            proc = subprocess.run([self.adb, *args], capture_output=True, timeout=timeout,
                                  creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise AdbError("The command timed out.")
        if proc.returncode != 0:
            raise AdbError(proc.stderr.decode("utf-8", "replace").strip() or "Command failed")
        return proc.stdout

    def run_device(self, serial: str, args: list[str], timeout: int | None = 60,
                   check: bool = True) -> tuple[int, str, str]:
        return self.run(["-s", serial, *args], timeout=timeout, check=check)

    def shell(self, serial: str, command: str, timeout: int | None = 120,
              check: bool = True) -> tuple[int, str, str]:
        return self.run_device(serial, ["shell", command], timeout=timeout, check=check)

    def stream(self, serial: str, args: list[str]) -> subprocess.Popen:
        """Start a long-running command (logcat, ...) and return the process."""
        full = ["-s", serial, *args]
        self._emit(format_command(self.adb, full))
        return subprocess.Popen([self.adb, *full], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)

    # ---- devices ----
    def devices(self) -> list[Device]:
        _, out, _ = self.run(["devices", "-l"], timeout=15)
        return parse_devices(out)


def human_size(n: float) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(n)
