"""Capture tab: screenshots and screen recording."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import capture


class CaptureTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.folder = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Pictures"))
        self.seconds = tk.IntVar(value=30)

        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Save to:").pack(side="left")
        ttk.Entry(row, textvariable=self.folder, width=60).pack(side="left", padx=6)
        ttk.Button(row, text="Browse...", command=self.browse).pack(side="left")

        shot = ttk.LabelFrame(self, text="Screenshot", padding=8)
        shot.pack(fill="x", pady=10)
        ttk.Button(shot, text="Take screenshot", command=self.screenshot).pack(side="left")
        ttk.Button(shot, text="Copy to clipboard", command=self.copy_screenshot).pack(
            side="left", padx=6)

        rec = ttk.LabelFrame(self, text="Screen recording", padding=8)
        rec.pack(fill="x")
        ttk.Label(rec, text="Seconds (max 180):").pack(side="left")
        ttk.Spinbox(rec, from_=1, to=180, textvariable=self.seconds, width=6).pack(
            side="left", padx=6)
        ttk.Button(rec, text="Record", command=self.record).pack(side="left")

    def browse(self):
        path = filedialog.askdirectory(initialdir=self.folder.get())
        if path:
            self.folder.set(path)

    def _target(self, extension: str) -> str:
        os.makedirs(self.folder.get(), exist_ok=True)
        return os.path.join(self.folder.get(), f"android-{capture.timestamp()}.{extension}")

    def _saved(self, path):
        messagebox.showinfo("Capture", f"Saved to {path}")

    def screenshot(self):
        dest = self._target("png")
        self.app.call(lambda adb, serial: capture.screenshot(adb, serial, dest), self._saved,
                      "Taking screenshot...")

    def copy_screenshot(self):
        # No dialog on success: the status bar is enough and the user can paste right away.
        self.app.call(capture.screenshot_to_clipboard,
                      lambda _: self.app.status.set("Screenshot copied to clipboard"),
                      "Copying screenshot...")

    def record(self):
        dest, seconds = self._target("mp4"), self.seconds.get()
        self.app.call(lambda adb, serial: capture.record(adb, serial, dest, seconds), self._saved,
                      f"Recording {seconds}s...")
