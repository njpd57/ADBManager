"""Shared Tk helpers: background execution, confirmation dialogs and read-only text widgets."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable


def run_bg(widget: tk.Misc, func: Callable[[], object],
           on_done: Callable[[object], None] | None = None,
           on_error: Callable[[Exception], None] | None = None) -> None:
    """Run `func` in a thread and deliver the result/error on the Tk main thread."""
    def worker():
        try:
            result = func()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            _deliver(widget, lambda: on_error(exc) if on_error else None)
        else:
            _deliver(widget, lambda: on_done(result) if on_done else None)

    threading.Thread(target=worker, daemon=True).start()


def _deliver(widget: tk.Misc, callback: Callable[[], None]) -> None:
    try:
        widget.after(0, callback)
    except tk.TclError:
        pass  # window closed


def confirm(parent: tk.Misc, title: str, message: str, command: str = "") -> bool:
    """Ask for confirmation, showing the exact adb command that will run."""
    text = message + (f"\n\nCommand:\n{command}" if command else "")
    return messagebox.askokcancel(title, text, parent=parent, icon="warning")


class TextView(ttk.Frame):
    """Read-only monospace text area with a vertical scrollbar."""

    def __init__(self, parent: tk.Misc, height: int = 12, wrap: str = "none"):
        super().__init__(parent)
        self.text = tk.Text(self, height=height, wrap=wrap, state="disabled",
                            font=("Consolas", 9))
        scroll = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def set(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", content)
        self.text.configure(state="disabled")

    def append(self, line: str, max_lines: int = 5000) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        count = int(self.text.index("end-1c").split(".")[0])
        if count > max_lines:
            self.text.delete("1.0", f"{count - max_lines}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self) -> None:
        self.set("")
