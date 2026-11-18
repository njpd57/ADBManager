"""Shell & Logcat tab: one-shot shell commands, live logcat viewer and reboot modes."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from .. import shell
from ..ui import TextView, confirm


class ShellTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self._proc = None
        self._history: list[str] = []
        self._history_pos = 0

        # ---- shell ----
        box = ttk.LabelFrame(self, text="Shell", padding=6)
        box.pack(fill="both", expand=True)
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.command = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.command)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.run_shell())
        entry.bind("<Up>", lambda _e: self._browse_history(-1))
        entry.bind("<Down>", lambda _e: self._browse_history(1))
        ttk.Button(row, text="Run", command=self.run_shell).pack(side="left", padx=4)
        self.output = TextView(box, height=8)
        self.output.pack(fill="both", expand=True, pady=(4, 0))

        # ---- logcat ----
        log = ttk.LabelFrame(self, text="Logcat", padding=6)
        log.pack(fill="both", expand=True, pady=8)
        bar = ttk.Frame(log)
        bar.pack(fill="x")
        self.level = tk.StringVar(value="V")
        self.tag = tk.StringVar()
        self.text_filter = tk.StringVar()
        ttk.Label(bar, text="Level").pack(side="left")
        ttk.Combobox(bar, textvariable=self.level, values=shell.LOG_LEVELS, state="readonly",
                     width=3).pack(side="left", padx=4)
        ttk.Label(bar, text="Tag").pack(side="left")
        ttk.Entry(bar, textvariable=self.tag, width=16).pack(side="left", padx=4)
        ttk.Label(bar, text="Contains").pack(side="left")
        ttk.Entry(bar, textvariable=self.text_filter, width=20).pack(side="left", padx=4)
        self.toggle = ttk.Button(bar, text="Start", command=self.toggle_logcat)
        self.toggle.pack(side="left", padx=4)
        ttk.Button(bar, text="Clear view", command=lambda: self.logview.clear()).pack(side="left")
        ttk.Button(bar, text="Clear device log", command=self.clear_device_log).pack(
            side="left", padx=4)
        self.logview = TextView(log, height=10)
        self.logview.pack(fill="both", expand=True, pady=(4, 0))

        # ---- reboot ----
        reboot = ttk.LabelFrame(self, text="Reboot", padding=6)
        reboot.pack(fill="x")
        self.mode = tk.StringVar(value="Normal")
        ttk.Combobox(reboot, textvariable=self.mode, values=list(shell.REBOOT_MODES),
                     state="readonly", width=12).pack(side="left")
        ttk.Button(reboot, text="Reboot", command=self.reboot).pack(side="left", padx=6)

    # ---- shell ----
    def _browse_history(self, step: int):
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + step))
        self.command.set(self._history[self._history_pos]
                         if self._history_pos < len(self._history) else "")

    def run_shell(self):
        command = self.command.get().strip()
        if not command:
            return
        self._history.append(command)
        self._history_pos = len(self._history)
        self.command.set("")
        self.output.append(f"$ {command}")
        self.app.call(lambda adb, serial: shell.run_shell(adb, serial, command),
                      lambda out: self.output.append(out or "(no output)"))

    # ---- logcat ----
    def toggle_logcat(self):
        if self._proc:
            self.stop_logcat()
            return
        serial = self.app.serial
        if not serial:
            self.app.call(lambda *_: None)  # shows the "no device" warning
            return
        args = shell.logcat_args(self.level.get(), self.tag.get().strip())
        self._proc = self.app.adb.stream(serial, args)
        self.toggle.configure(text="Stop")
        threading.Thread(target=self._read_logcat, args=(self._proc,), daemon=True).start()

    def _read_logcat(self, proc):
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if shell.line_matches(line, self.text_filter.get()):
                try:
                    self.after(0, self.logview.append, line)
                except tk.TclError:
                    return
        try:
            self.after(0, self._logcat_ended, proc)
        except tk.TclError:
            pass

    def _logcat_ended(self, proc):
        if self._proc is proc:
            self._proc = None
            self.toggle.configure(text="Start")

    def stop_logcat(self):
        proc, self._proc = self._proc, None
        if proc:
            proc.terminate()
        self.toggle.configure(text="Start")

    def clear_device_log(self):
        self.app.call(shell.clear_logcat)

    # ---- reboot ----
    def reboot(self):
        mode = self.mode.get()
        extra = " " + " ".join(shell.REBOOT_MODES[mode]) if shell.REBOOT_MODES[mode] else ""
        if confirm(self, "Reboot", f"Reboot the device ({mode})?", f"adb reboot{extra}"):
            self.app.call(lambda adb, serial: shell.reboot(adb, serial, mode), None, "Rebooting...")
