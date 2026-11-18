"""Backup & Permissions tab: adb backup/restore, runtime permissions, sideload and fastboot."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import backup
from ..ui import TextView, confirm


class BackupTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app

        # ---- backup / restore ----
        box = ttk.LabelFrame(self, text="Backup / restore (confirm on the device screen)", padding=8)
        box.pack(fill="x")
        self.package = tk.StringVar()
        self.include_apk = tk.BooleanVar(value=True)
        self.include_shared = tk.BooleanVar()
        ttk.Label(box, text="Package (empty = all):").pack(side="left")
        ttk.Entry(box, textvariable=self.package, width=32).pack(side="left", padx=6)
        ttk.Checkbutton(box, text="APKs", variable=self.include_apk).pack(side="left")
        ttk.Checkbutton(box, text="Shared storage", variable=self.include_shared).pack(
            side="left", padx=6)
        ttk.Button(box, text="Backup...", command=self.backup).pack(side="left")
        ttk.Button(box, text="Restore...", command=self.restore).pack(side="left", padx=4)

        # ---- permissions ----
        perms = ttk.LabelFrame(self, text="Runtime permissions", padding=8)
        perms.pack(fill="both", expand=True, pady=8)
        bar = ttk.Frame(perms)
        bar.pack(fill="x")
        self.perm_package = tk.StringVar()
        ttk.Label(bar, text="Package:").pack(side="left")
        ttk.Entry(bar, textvariable=self.perm_package, width=36).pack(side="left", padx=6)
        ttk.Button(bar, text="Load", command=self.load_permissions).pack(side="left")
        ttk.Button(bar, text="Grant", command=lambda: self.set_permission(True)).pack(
            side="left", padx=4)
        ttk.Button(bar, text="Revoke", command=lambda: self.set_permission(False)).pack(
            side="left")
        self.tree = ttk.Treeview(perms, columns=("granted",), height=8)
        self.tree.heading("#0", text="Permission")
        self.tree.heading("granted", text="Granted")
        self.tree.column("granted", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=(6, 0))

        # ---- sideload / fastboot ----
        other = ttk.LabelFrame(self, text="Sideload & fastboot", padding=8)
        other.pack(fill="x")
        ttk.Button(other, text="Sideload ZIP... (recovery mode)", command=self.sideload).pack(
            side="left")
        ttk.Button(other, text="fastboot devices", command=lambda: self.fastboot(["devices"])
                   ).pack(side="left", padx=6)
        ttk.Button(other, text="fastboot reboot", command=self.fastboot_reboot).pack(side="left")
        self.result = TextView(self, height=4)
        self.result.pack(fill="x", pady=(8, 0))

    def _show(self, result):
        self.result.set(str(result))

    # ---- backup ----
    def backup(self):
        path = filedialog.asksaveasfilename(defaultextension=".ab",
                                            filetypes=[("Android backup", "*.ab")])
        if path:
            package = self.package.get().strip() or None
            self.app.call(lambda adb, s: backup.backup(
                adb, s, path, package, self.include_apk.get(), self.include_shared.get()),
                self._show, "Backing up (confirm on the device)...")

    def restore(self):
        path = filedialog.askopenfilename(filetypes=[("Android backup", "*.ab")])
        if path and confirm(self, "Restore", "Restore this backup onto the device?",
                            f"adb restore {path}"):
            self.app.call(lambda adb, s: backup.restore(adb, s, path), self._show,
                          "Restoring (confirm on the device)...")

    # ---- permissions ----
    def load_permissions(self):
        package = self.perm_package.get().strip()
        if not package:
            return

        def show(perms):
            self.tree.delete(*self.tree.get_children())
            for name, granted in sorted(perms.items()):
                self.tree.insert("", "end", text=name, values=("yes" if granted else "no",))
        self.app.call(lambda adb, s: backup.list_permissions(adb, s, package), show,
                      "Reading permissions...")

    def set_permission(self, grant: bool):
        package = self.perm_package.get().strip()
        selected = self.tree.selection()
        if not package or not selected:
            messagebox.showinfo("Permissions", "Load a package and select permissions first.")
            return
        names = [self.tree.item(i, "text") for i in selected]
        verb = "grant" if grant else "revoke"
        if not confirm(self, "Permissions", f"{verb.title()} {len(names)} permission(s)?",
                       f"adb shell pm {verb} {package} <permission>"):
            return

        def work(adb, serial):
            for name in names:
                backup.set_permission(adb, serial, package, name, grant)
        self.app.call(work, lambda _r: self.load_permissions(), "Updating permissions...")

    # ---- sideload / fastboot ----
    def sideload(self):
        path = filedialog.askopenfilename(filetypes=[("ZIP", "*.zip")])
        if path and confirm(self, "Sideload", "Sideload this package? The device must be in "
                            "recovery 'Apply update from ADB' mode.", f"adb sideload {path}"):
            self.app.call(lambda adb, s: backup.sideload(adb, s, path), self._show,
                          "Sideloading...")

    def fastboot(self, args):
        self.app.call(lambda adb, _s: backup.fastboot(adb, args), self._show,
                      need_device=False)

    def fastboot_reboot(self):
        if confirm(self, "fastboot", "Reboot the device out of fastboot?", "fastboot reboot"):
            self.fastboot(["reboot"])
