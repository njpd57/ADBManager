"""Device tab: connect/pair over Wi-Fi and show device information."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import devices
from ..ui import TextView


class DevicesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app

        wifi = ttk.LabelFrame(self, text="Wi-Fi connection", padding=8)
        wifi.pack(fill="x")
        self.address = tk.StringVar()
        self.code = tk.StringVar()
        ttk.Label(wifi, text="IP:port").grid(row=0, column=0, sticky="w")
        ttk.Entry(wifi, textvariable=self.address, width=24).grid(row=0, column=1, padx=6)
        ttk.Label(wifi, text="Pairing code").grid(row=0, column=2, sticky="w")
        ttk.Entry(wifi, textvariable=self.code, width=10).grid(row=0, column=3, padx=6)
        ttk.Button(wifi, text="Connect", command=self.connect).grid(row=0, column=4, padx=2)
        ttk.Button(wifi, text="Pair", command=self.pair).grid(row=0, column=5, padx=2)
        ttk.Button(wifi, text="Disconnect", command=self.disconnect).grid(row=0, column=6, padx=2)
        ttk.Button(wifi, text="Enable TCP/IP (USB)", command=self.tcpip).grid(
            row=0, column=7, padx=2)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Button(bar, text="Load device info", command=self.load_info).pack(side="left")
        self.info = TextView(self, height=18)
        self.info.pack(fill="both", expand=True)

    def _report(self, result) -> None:
        self.app.refresh_devices()
        self.info.set(str(result))

    def connect(self):
        address = self.address.get().strip()
        if address:
            self.app.call(lambda adb, _s: devices.connect(adb, address), self._report,
                          "Connecting...", need_device=False)

    def pair(self):
        address, code = self.address.get().strip(), self.code.get().strip()
        if address and code:
            self.app.call(lambda adb, _s: devices.pair(adb, address, code), self._report,
                          "Pairing...", need_device=False)

    def disconnect(self):
        address = self.address.get().strip() or None
        self.app.call(lambda adb, _s: devices.disconnect(adb, address), self._report,
                      need_device=False)

    def tcpip(self):
        self.app.call(lambda adb, serial: devices.tcpip(adb, serial), self._report)

    def load_info(self):
        def show(info):
            self.info.set("\n".join(f"{key:<18}{value}" for key, value in info.items()))
        self.app.call(devices.device_info, show, "Reading device info...")
