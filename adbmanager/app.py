"""Main window: device selector on top and one tab per module."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .adb import Adb, AdbError, Device
from .tabs.apps_tab import AppsTab
from .tabs.backup_tab import BackupTab
from .tabs.capture_tab import CaptureTab
from .tabs.devices_tab import DevicesTab
from .tabs.log_tab import LogTab
from .tabs.shell_tab import ShellTab
from .tabs.system_tab import SystemTab
from .ui import run_bg

POLL_MS = 5000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ADBManager")
        self.geometry("1000x680")
        self.minsize(820, 520)
        try:
            self.adb = Adb()
        except AdbError as exc:
            messagebox.showerror("adb not found", str(exc))
            raise SystemExit(1)

        self._devices: list[Device] = []
        self.status = tk.StringVar(value="Ready")
        self._build_header()
        self._build_tabs()
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken").pack(
            side="bottom", fill="x")
        self.refresh_devices()
        self.after(POLL_MS, self._poll)

    # ---- layout ----
    def _build_header(self) -> None:
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="Device:").pack(side="left")
        self.device_var = tk.StringVar()
        self.combo = ttk.Combobox(bar, textvariable=self.device_var, state="readonly", width=48)
        self.combo.pack(side="left", padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh_devices).pack(side="left")

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log_tab = LogTab(self.notebook, self)
        tabs = [
            ("Device", DevicesTab(self.notebook, self)),
            ("Apps", AppsTab(self.notebook, self)),
            ("Capture", CaptureTab(self.notebook, self)),
            ("Shell & Logcat", ShellTab(self.notebook, self)),
            ("System", SystemTab(self.notebook, self)),
            ("Backup & Permissions", BackupTab(self.notebook, self)),
            ("Log & Console", self.log_tab),
        ]
        for title, tab in tabs:
            self.notebook.add(tab, text=title)
        self.adb.add_listener(lambda line: self.after(0, self.log_tab.log, line))

    # ---- devices ----
    @property
    def serial(self) -> str | None:
        label = self.device_var.get()
        for device in self._devices:
            if device.label == label and device.state == "device":
                return device.serial
        return None

    def refresh_devices(self) -> None:
        run_bg(self, self.adb.devices, self._set_devices,
               lambda exc: self.status.set(f"Error: {exc}"))

    def _set_devices(self, devices: list[Device]) -> None:
        previous = self.device_var.get()
        changed = [d.label for d in devices] != [d.label for d in self._devices]
        self._devices = devices
        labels = [d.label for d in devices]
        self.combo["values"] = labels
        if previous in labels:
            self.device_var.set(previous)
        else:
            ready = [d.label for d in devices if d.state == "device"]
            self.device_var.set(ready[0] if ready else (labels[0] if labels else ""))
        if changed:
            self.status.set(f"{len(devices)} device(s) found" if devices else "No devices connected")

    def _poll(self) -> None:
        self.refresh_devices()
        self.after(POLL_MS, self._poll)

    # ---- task runner used by every tab ----
    def call(self, func: Callable[[Adb, str], object],
             on_done: Callable[[object], None] | None = None,
             message: str = "Working...", need_device: bool = True) -> None:
        """Run `func(adb, serial)` in the background, reporting errors in a dialog."""
        serial = self.serial
        if need_device and not serial:
            messagebox.showwarning("No device", "Connect and authorize a device first.")
            return
        self.status.set(message)

        def done(result):
            self.status.set("Done")
            if on_done:
                on_done(result)

        def failed(exc):
            self.status.set(f"Error: {exc}")
            messagebox.showerror("Error", str(exc))

        run_bg(self, lambda: func(self.adb, serial), done, failed)
