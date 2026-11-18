"""System tab: live monitor, processes and system properties."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import system
from ..adb import human_size
from ..ui import TextView

MONITOR_MS = 3000


class SystemTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self._monitoring = False
        self._busy = False
        self.battery = tk.StringVar(value="-")
        self.ram = tk.StringVar(value="-")
        self.network = tk.StringVar(value="-")

        live = ttk.LabelFrame(self, text="Live monitor", padding=8)
        live.pack(fill="x")
        for row, (label, var) in enumerate((("Battery", self.battery), ("RAM", self.ram),
                                            ("Network", self.network))):
            ttk.Label(live, text=label + ":", width=10).grid(row=row, column=0, sticky="w")
            ttk.Label(live, textvariable=var).grid(row=row, column=1, sticky="w")
        self.toggle = ttk.Button(live, text="Start monitor", command=self.toggle_monitor)
        self.toggle.grid(row=0, column=2, padx=20)

        self.views = ttk.Notebook(self)
        self.views.pack(fill="both", expand=True, pady=8)
        self.top_view = TextView(self.views)
        self.views.add(self.top_view, text="Top (CPU)")

        procs = ttk.Frame(self.views)
        self.views.add(procs, text="Processes")
        ttk.Button(procs, text="Load processes", command=self.load_processes).pack(anchor="w")
        self.proc_view = TextView(procs)
        self.proc_view.pack(fill="both", expand=True)

        props = ttk.Frame(self.views)
        self.views.add(props, text="Properties")
        bar = ttk.Frame(props)
        bar.pack(fill="x")
        ttk.Button(bar, text="Load properties", command=self.load_props).pack(side="left")
        self.prop_filter = tk.StringVar()
        ttk.Entry(bar, textvariable=self.prop_filter, width=24).pack(side="left", padx=6)
        ttk.Label(bar, text="(filter)").pack(side="left")
        self.prop_view = TextView(props)
        self.prop_view.pack(fill="both", expand=True)
        self._props_raw = ""
        self.prop_filter.trace_add("write", lambda *_: self._show_props())

    # ---- monitor ----
    def toggle_monitor(self):
        self._monitoring = not self._monitoring
        self.toggle.configure(text="Stop monitor" if self._monitoring else "Start monitor")
        if self._monitoring:
            self._tick()

    def _tick(self):
        if not self._monitoring:
            return
        if not self._busy and self.app.serial:
            self._busy = True
            serial = self.app.serial

            def done(sample):
                self._busy = False
                self.battery.set(sample["Battery"])
                self.ram.set(sample["RAM"])
                self.network.set(sample["Network"])
                self.top_view.set(sample["Top"])

            from ..ui import run_bg
            run_bg(self, lambda: system.snapshot(self.app.adb, serial), done,
                   lambda _e: setattr(self, "_busy", False))
        self.after(MONITOR_MS, self._tick)

    # ---- processes ----
    def load_processes(self):
        def show(rows):
            lines = [f"{'PID':>7}  {'USER':<12}{'RSS':>10}  NAME"]
            lines += [f"{pid:>7}  {user:<12}{human_size(rss):>10}  {name}"
                      for pid, user, rss, name in rows]
            self.proc_view.set("\n".join(lines))
        self.app.call(system.processes, show, "Reading processes...")

    # ---- properties ----
    def load_props(self):
        def show(raw):
            self._props_raw = raw
            self._show_props()
        self.app.call(system.getprop, show, "Reading properties...")

    def _show_props(self):
        text = self.prop_filter.get().lower()
        lines = [l for l in self._props_raw.splitlines() if text in l.lower()]
        self.prop_view.set("\n".join(lines))
