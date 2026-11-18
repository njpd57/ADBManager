"""Package management: list, install, uninstall, disable, clear data, force-stop, extract APK."""
from __future__ import annotations

import os
import shlex
import tempfile
import zipfile

from .adb import Adb, AdbError

SCOPES = {
    "User": "-3",
    "System": "-s",
    "Disabled": "-d",
    "All": "",
}


def parse_packages(output: str) -> list[str]:
    """Parse `pm list packages` lines (`package:name`)."""
    names = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            names.append(line[len("package:"):].strip())
    return sorted(names, key=str.lower)


def parse_package_paths(output: str) -> list[str]:
    """Parse `pm path <pkg>` into APK paths on the device."""
    return [l.strip()[len("package:"):] for l in output.splitlines()
            if l.strip().startswith("package:")]


def list_packages(adb: Adb, serial: str, scope: str = "User") -> list[str]:
    flag = SCOPES[scope]
    _, out, _ = adb.shell(serial, f"pm list packages {flag}".strip(), timeout=60)
    return parse_packages(out)


def _check_success(output: str) -> str:
    text = output.strip()
    if "Success" not in text:
        raise AdbError(text or "Operation failed")
    return text


def collect_apks(path: str, workdir: str) -> list[str]:
    """Return the APK files to install from an .apk, a folder or an .apks/.xapk/.zip bundle."""
    if os.path.isdir(path):
        apks = sorted(os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".apk"))
    elif path.lower().endswith((".apks", ".xapk", ".zip")):
        with zipfile.ZipFile(path) as bundle:
            members = [m for m in bundle.namelist() if m.lower().endswith(".apk")]
            for member in members:
                target = os.path.realpath(os.path.join(workdir, member))
                if not target.startswith(os.path.realpath(workdir) + os.sep):
                    raise AdbError(f"Unsafe path in archive: {member}")
            bundle.extractall(workdir, members)
        apks = sorted(os.path.join(workdir, m) for m in members)
    else:
        apks = [path]
    if not apks:
        raise AdbError("No APK files found.")
    return apks


def install(adb: Adb, serial: str, path: str, downgrade: bool = False,
            grant_all: bool = False) -> str:
    flags = ["-r"] + (["-d"] if downgrade else []) + (["-g"] if grant_all else [])
    with tempfile.TemporaryDirectory() as workdir:
        apks = collect_apks(path, workdir)
        verb = "install" if len(apks) == 1 else "install-multiple"
        _, out, err = adb.run_device(serial, [verb, *flags, *apks], timeout=None, check=False)
    return _check_success(out + "\n" + err)


def uninstall(adb: Adb, serial: str, package: str, keep_data: bool = False,
              system_for_user: bool = False) -> str:
    """Uninstall a package. `system_for_user` removes system apps for user 0 only."""
    if system_for_user:
        flag = "-k " if keep_data else ""
        _, out, err = adb.shell(serial, f"pm uninstall {flag}--user 0 {shlex.quote(package)}",
                                check=False)
    else:
        args = ["uninstall"] + (["-k"] if keep_data else []) + [package]
        _, out, err = adb.run_device(serial, args, timeout=120, check=False)
    return _check_success(out + "\n" + err)


def set_enabled(adb: Adb, serial: str, package: str, enabled: bool) -> str:
    command = "pm enable" if enabled else "pm disable-user --user 0"
    return adb.shell(serial, f"{command} {shlex.quote(package)}")[1].strip()


def clear_data(adb: Adb, serial: str, package: str) -> str:
    return _check_success(adb.shell(serial, f"pm clear {shlex.quote(package)}", check=False)[1])


def force_stop(adb: Adb, serial: str, package: str) -> None:
    adb.shell(serial, f"am force-stop {shlex.quote(package)}")


def launch(adb: Adb, serial: str, package: str) -> None:
    adb.shell(serial, f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1")


def extract_apk(adb: Adb, serial: str, package: str, dest_dir: str) -> list[str]:
    """Pull every APK of `package` (base + splits) into `dest_dir`; return local file names."""
    _, out, _ = adb.shell(serial, f"pm path {shlex.quote(package)}")
    paths = parse_package_paths(out)
    if not paths:
        raise AdbError(f"Package not found: {package}")
    os.makedirs(dest_dir, exist_ok=True)
    pulled = []
    for index, remote in enumerate(paths):
        name = f"{package}.apk" if len(paths) == 1 else f"{package}-{index}-{os.path.basename(remote)}"
        local = os.path.join(dest_dir, name)
        adb.run_device(serial, ["pull", remote, local], timeout=None)
        pulled.append(local)
    return pulled


# ---------------------------------------------------------------------------
# App information (sizes, dates, installer, state)
# ---------------------------------------------------------------------------
import json  # noqa: E402
import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402


@dataclass
class AppInfo:
    package: str
    apk_path: str = ""
    uid: str = ""
    app_size: int = 0
    data_size: int = 0
    cache_size: int = 0
    installed: str = ""
    updated: str = ""
    installer: str = ""
    version: str = ""
    is_system: bool = False
    enabled: bool = True
    running: bool = False

    @property
    def total_size(self) -> int:
        return self.app_size + self.data_size + self.cache_size


def parse_diskstats(output: str) -> dict[str, tuple[int, int, int]]:
    """Parse `dumpsys diskstats` parallel arrays into {package: (app, data, cache)} bytes."""
    arrays: dict[str, list] = {}
    for line in output.splitlines():
        match = re.match(r"^(Package Names|App Sizes|App Data Sizes|Cache Sizes):\s*(\[.*\])\s*$",
                         line.strip())
        if match:
            try:
                arrays[match.group(1)] = json.loads(match.group(2))
            except ValueError:
                pass
    names = arrays.get("Package Names", [])
    sizes = [arrays.get(k, []) for k in ("App Sizes", "App Data Sizes", "Cache Sizes")]
    result = {}
    for index, name in enumerate(names):
        values = tuple(int(col[index]) if index < len(col) else 0 for col in sizes)
        result[name] = values
    return result


def parse_package_list_full(output: str) -> dict[str, tuple[str, str]]:
    """Parse `pm list packages -f -U` into {package: (apk_path, uid)}."""
    result = {}
    for line in output.splitlines():
        match = re.match(r"^package:(.+)=(\S+?)(?:\s+uid:(\d+))?\s*$", line.strip())
        if match:
            result[match.group(2)] = (match.group(1), match.group(3) or "")
    return result


def parse_package_details(output: str) -> dict[str, dict[str, object]]:
    """Parse `dumpsys package packages` blocks into per-package metadata."""
    details: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for line in output.splitlines():
        header = re.match(r"^  Package \[(.+?)\]", line)
        if header:
            current = {}
            details[header.group(1)] = current
            continue
        if current is None:
            continue
        text = line.strip()
        for key, field in (("versionName=", "version"), ("lastUpdateTime=", "updated"),
                           ("installerPackageName=", "installer"),
                           ("firstInstallTime=", "installed")):
            if text.startswith(key) and field not in current:
                current[field] = text[len(key):]
        if text.startswith("User 0:") and "enabled" not in current:
            state = re.search(r"\benabled=(\d+)", text)
            # 0 = default (enabled), 1 = enabled, 2 = disabled, 3 = disabled by user
            current["enabled"] = not state or state.group(1) in ("0", "1")
    return details


def parse_running(output: str) -> set[str]:
    """Process names from `ps -A -o NAME` (the process name starts with the package)."""
    return {line.split(":")[0].strip() for line in output.splitlines()[1:] if line.strip()}


def _clean_installer(value: object) -> str:
    text = str(value)
    return "" if text in ("null", "None") else text


def list_app_infos(adb: Adb, serial: str, scope: str = "User") -> list[AppInfo]:
    """Packages of `scope` with sizes, dates, installer and state, using 4 batched calls."""
    names = list_packages(adb, serial, scope)
    _, paths_out, _ = adb.shell(serial, "pm list packages -f -U", timeout=60, check=False)
    _, disk_out, _ = adb.shell(serial, "dumpsys diskstats", timeout=60, check=False)
    _, pkg_out, _ = adb.shell(serial, "dumpsys package packages", timeout=120, check=False)
    _, ps_out, _ = adb.shell(serial, "ps -A -o NAME", timeout=30, check=False)
    paths = parse_package_list_full(paths_out)
    sizes = parse_diskstats(disk_out)
    details = parse_package_details(pkg_out)
    running = parse_running(ps_out)
    infos = []
    for name in names:
        path, uid = paths.get(name, ("", ""))
        app, data, cache = sizes.get(name, (0, 0, 0))
        extra = details.get(name, {})
        infos.append(AppInfo(
            package=name, apk_path=path, uid=uid, app_size=app, data_size=data,
            cache_size=cache, installed=str(extra.get("installed", "")),
            updated=str(extra.get("updated", "")), installer=_clean_installer(extra.get("installer", "")),
            version=str(extra.get("version", "")),
            is_system=path.startswith(("/system", "/product", "/vendor", "/apex", "/system_ext")),
            enabled=bool(extra.get("enabled", True)), running=name in running))
    return infos
