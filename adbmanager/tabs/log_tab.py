"""Log & Console tab: history of executed commands and a raw adb console."""
from __future__ import annotations

import shlex
import time
import tkinter as tk
from tkinter import ttk

from ..ui import TextView


class LogTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self._history: list[str] = []
        self._pos = 0

        console = ttk.LabelFrame(self, text="adb console (arguments after `adb`, device is added automatically)",
                                 padding=6)
        console.pack(fill="x")
        self.command = tk.StringVar()
        entry = ttk.Entry(console, textvariable=self.command)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.run())
        entry.bind("<Up>", lambda _e: self._browse(-1))
        entry.bind("<Down>", lambda _e: self._browse(1))
        ttk.Button(console, text="Run", command=self.run).pack(side="left", padx=4)
        self.output = TextView(self, height=10)
        self.output.pack(fill="x", pady=6)

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="Executed commands").pack(side="left")
        ttk.Button(header, text="Clear", command=lambda: self.history_view.clear()).pack(
            side="right")
        self.history_view = TextView(self)
        self.history_view.pack(fill="both", expand=True)

    def log(self, line: str) -> None:
        self.history_view.append(f"[{time.strftime('%H:%M:%S')}] {line}")

    def _browse(self, step: int) -> None:
        if not self._history:
            return
        self._pos = max(0, min(len(self._history), self._pos + step))
        self.command.set(self._history[self._pos] if self._pos < len(self._history) else "")

    def run(self) -> None:
        text = self.command.get().strip()
        if not text:
            return
        try:
            args = shlex.split(text)
        except ValueError as exc:
            self.output.set(f"Invalid command: {exc}")
            return
        self._history.append(text)
        self._pos = len(self._history)
        self.command.set("")
        serial = self.app.serial
        full = ["-s", serial, *args] if serial else args

        def work(adb, _serial):
            _, out, err = adb.run(full, timeout=120, check=False)
            return (out + ("\n" + err if err else "")).rstrip()

        self.app.call(work, lambda out: self.output.set(f"$ adb {text}\n{out}"),
                      need_device=False)
