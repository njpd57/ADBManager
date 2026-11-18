"""Device operations: connect/pair/disconnect and device information."""
from __future__ import annotations

import re

from .adb import Adb, AdbError
from .system import parse_battery, parse_meminfo, parse_df


def parse_getprop(output: str) -> dict[str, str]:
    """Parse `getprop` lines formatted as `[key]: [value]`."""
    props = {}
    for line in output.splitlines():
        match = re.match(r"^\[(.+?)\]: \[(.*)\]$", line.strip())
        if match:
            props[match.group(1)] = match.group(2)
    return props


def connect(adb: Adb, address: str) -> str:
    _, out, err = adb.run(["connect", address], timeout=20)
    text = (out + err).strip()
    if "cannot" in text.lower() or "failed" in text.lower():
        raise AdbError(text)
    return text


def pair(adb: Adb, address: str, code: str) -> str:
    _, out, err = adb.run(["pair", address, code], timeout=30)
    text = (out + err).strip()
    if "success" not in text.lower():
        raise AdbError(text or "Pairing failed")
    return text


def disconnect(adb: Adb, address: str | None = None) -> str:
    args = ["disconnect"] + ([address] if address else [])
    _, out, err = adb.run(args, timeout=15)
    return (out + err).strip()


def tcpip(adb: Adb, serial: str, port: int = 5555) -> str:
    _, out, err = adb.run_device(serial, ["tcpip", str(port)], timeout=15)
    return (out + err).strip()


def device_info(adb: Adb, serial: str) -> dict[str, str]:
    """Return an ordered dict of human-readable device information."""
    _, props_out, _ = adb.shell(serial, "getprop", timeout=20)
    props = parse_getprop(props_out)
    _, battery_out, _ = adb.shell(serial, "dumpsys battery", timeout=20, check=False)
    battery = parse_battery(battery_out)
    sep = "@@MEM@@"
    _, out, _ = adb.shell(serial, f"df -k /data; echo {sep}; cat /proc/meminfo", timeout=20,
                          check=False)
    df_out, _, mem_out = out.partition(sep)
    disk = parse_df(df_out)
    mem = parse_meminfo(mem_out)

    info = {
        "Serial": serial,
        "Manufacturer": props.get("ro.product.manufacturer", "?"),
        "Model": props.get("ro.product.model", "?"),
        "Device": props.get("ro.product.device", "?"),
        "Android": props.get("ro.build.version.release", "?"),
        "SDK": props.get("ro.build.version.sdk", "?"),
        "Security patch": props.get("ro.build.version.security_patch", "?"),
        "Build": props.get("ro.build.display.id", "?"),
        "ABI": props.get("ro.product.cpu.abi", "?"),
        "Battery": f"{battery.get('level', '?')}% ({battery.get('status', '?')})",
        "Storage (/data)": disk.describe(),
        "RAM": mem.describe(),
    }
    return info
