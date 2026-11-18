"""System and performance information parsers and queries."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .adb import Adb, human_size

_BATTERY_STATUS = {"1": "unknown", "2": "charging", "3": "discharging", "4": "not charging",
                   "5": "full"}


@dataclass
class Usage:
    total: int = 0
    used: int = 0
    free: int = 0

    def describe(self) -> str:
        if not self.total:
            return "?"
        return f"{human_size(self.used)} used / {human_size(self.total)} ({human_size(self.free)} free)"


def parse_battery(output: str) -> dict[str, str]:
    """Parse `dumpsys battery`; temperature is converted to Celsius."""
    values = {}
    for line in output.splitlines():
        match = re.match(r"^\s*([\w ]+):\s*(.*)$", line)
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    if "status" in values:
        values["status"] = _BATTERY_STATUS.get(values["status"], values["status"])
    if "temperature" in values and values["temperature"].lstrip("-").isdigit():
        values["temperature"] = f"{int(values['temperature']) / 10:.1f} °C"
    return values


def parse_df(output: str) -> Usage:
    """Parse the last data line of `df -k`."""
    for line in reversed([l for l in output.splitlines() if l.strip()]):
        tokens = line.split()
        if len(tokens) >= 5 and tokens[-5].isdigit() and tokens[-4].isdigit():
            return Usage(*(int(x) * 1024 for x in tokens[-5:-2]))
    return Usage()


def parse_meminfo(output: str) -> Usage:
    values = {}
    for line in output.splitlines():
        match = re.match(r"(MemTotal|MemAvailable):\s+(\d+)\s*kB", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    total = values.get("MemTotal", 0)
    free = values.get("MemAvailable", 0)
    return Usage(total, total - free, free)


def parse_ps(output: str) -> list[tuple[str, str, int, str]]:
    """Parse `ps -A -o PID,USER,RSS,NAME` into (pid, user, rss_bytes, name) sorted by RSS."""
    rows = []
    for line in output.splitlines()[1:]:
        tokens = line.split(None, 3)
        if len(tokens) == 4 and tokens[0].isdigit() and tokens[2].isdigit():
            rows.append((tokens[0], tokens[1], int(tokens[2]) * 1024, tokens[3].strip()))
    return sorted(rows, key=lambda row: row[2], reverse=True)


def parse_ip_addresses(output: str) -> list[tuple[str, str]]:
    """Parse `ip -f inet addr` into (interface, address) skipping loopback."""
    result = []
    for match in re.finditer(r"^\d+:\s+(\S+?):.*?\n(?:.*\n)*?\s+inet\s+(\S+)", output, re.M):
        if match.group(1) != "lo":
            result.append((match.group(1), match.group(2)))
    return result


def getprop(adb: Adb, serial: str) -> str:
    return adb.shell(serial, "getprop", timeout=20)[1]


def processes(adb: Adb, serial: str) -> list[tuple[str, str, int, str]]:
    return parse_ps(adb.shell(serial, "ps -A -o PID,USER,RSS,NAME", timeout=20, check=False)[1])


def snapshot(adb: Adb, serial: str) -> dict[str, str]:
    """One sample for the live monitor: battery, memory, network and top CPU consumers."""
    sep = "@@SEP@@"
    command = (f"dumpsys battery; echo {sep}; cat /proc/meminfo; echo {sep}; "
               f"ip -f inet addr; echo {sep}; top -b -n 1 -m 8 2>/dev/null")
    _, out, _ = adb.shell(serial, command, timeout=30, check=False)
    battery_out, mem_out, ip_out, top_out = (out.split(sep) + [""] * 4)[:4]
    battery = parse_battery(battery_out)
    return {
        "Battery": f"{battery.get('level', '?')}% - {battery.get('status', '?')} - "
                   f"{battery.get('temperature', '?')}",
        "RAM": parse_meminfo(mem_out).describe(),
        "Network": ", ".join(f"{i}: {a}" for i, a in parse_ip_addresses(ip_out)) or "?",
        "Top": top_out.strip(),
    }
