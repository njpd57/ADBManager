"""Apps tab: sortable table with icons, sizes and metadata, plus package actions."""
from __future__ import annotations

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk

from .. import apps
from ..adb import human_size
from ..icons import IconExtractor
from ..ui import confirm

ICON_PX = 36

# column id -> (heading, width, anchor, sort key, numeric)
COLUMNS = {
    "package": ("Package", 230, "w"),
    "total": ("Total", 80, "e"),
    "app": ("App", 80, "e"),
    "data": ("Data", 80, "e"),
    "cache": ("Cache", 70, "e"),
    "installed": ("Installed", 130, "w"),
    "updated": ("Updated", 130, "w"),
    "installer": ("Installer", 130, "w"),
    "type": ("Type", 60, "w"),
    "state": ("State", 110, "w"),
}
# Sort keys operate on AppRow; numeric columns sort descending on first click.
SORT_KEYS = {
    "#0": lambda r: (r.label or r.package).lower(),
    "package": lambda r: r.package.lower(),
    "total": lambda r: r.info.total_size,
    "app": lambda r: r.info.app_size,
    "data": lambda r: r.info.data_size,
    "cache": lambda r: r.info.cache_size,
    "installed": lambda r: r.info.installed,
    "updated": lambda r: r.info.updated,
    "installer": lambda r: r.info.installer.lower(),
    "type": lambda r: r.info.is_system,
    "state": lambda r: (r.info.enabled, r.info.running),
}
DESCENDING_FIRST = {"total", "app", "data", "cache", "installed", "updated"}


class AppRow:
    """An AppInfo plus UI-only data (label and icon)."""

    def __init__(self, info: apps.AppInfo):
        self.info = info
        self.label = ""
        self.image: tk.PhotoImage | None = None

    def __getattr__(self, name):  # delegate to the AppInfo (package, total_size, ...)
        return getattr(self.info, name)


class AppsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self._rows: dict[str, AppRow] = {}
        self._sort = ("total", True)
        self._generation = 0
        self._extractor: IconExtractor | None = None
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._loaded_for: tuple[str, str] | None = None

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.scope = tk.StringVar(value="User")
        scope = ttk.Combobox(top, textvariable=self.scope, values=list(apps.SCOPES),
                             state="readonly", width=10)
        scope.pack(side="left")
        scope.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        ttk.Button(top, text="Reload", command=self.reload).pack(side="left", padx=4)
        ttk.Label(top, text="Filter:").pack(side="left", padx=(12, 2))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(top, textvariable=self.filter, width=28).pack(side="left")
        ttk.Button(top, text="Install APK...", command=self.install_file).pack(side="right")
        ttk.Button(top, text="Install folder (split)...", command=self.install_folder).pack(
            side="right", padx=4)

        style = ttk.Style(self)
        style.configure("Apps.Treeview", rowheight=ICON_PX + 6)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(body, columns=list(COLUMNS), style="Apps.Treeview",
                                 selectmode="extended")
        self.tree.heading("#0", text="Name", command=lambda: self._sort_by("#0"))
        self.tree.column("#0", width=230, minwidth=120)
        for column, (title, width, anchor) in COLUMNS.items():
            self.tree.heading(column, text=title, command=lambda c=column: self._sort_by(c))
            self.tree.column(column, width=width, anchor=anchor, minwidth=40)
        yscroll = ttk.Scrollbar(body, command=self.tree.yview)
        xscroll = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        xscroll.pack(side="bottom", fill="x")
        yscroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.keep_data = tk.BooleanVar()
        self.system_user = tk.BooleanVar()
        ttk.Button(actions, text="Open", command=self.launch).pack(side="left")
        ttk.Button(actions, text="Force stop", command=self.force_stop).pack(side="left", padx=4)
        ttk.Button(actions, text="Clear data", command=self.clear_data).pack(side="left")
        ttk.Button(actions, text="Disable", command=lambda: self.set_enabled(False)).pack(
            side="left", padx=4)
        ttk.Button(actions, text="Enable", command=lambda: self.set_enabled(True)).pack(side="left")
        ttk.Button(actions, text="Extract APK...", command=self.extract).pack(side="left", padx=4)
        ttk.Button(actions, text="Uninstall", command=self.uninstall).pack(side="left")
        ttk.Checkbutton(actions, text="Keep data", variable=self.keep_data).pack(
            side="left", padx=(10, 0))
        ttk.Checkbutton(actions, text="System app (user 0)", variable=self.system_user).pack(
            side="left", padx=6)

        # Load the list automatically when the tab is shown or the device changes.
        self.bind("<Map>", lambda _e: self.autoload())
        self.app.combo.bind("<<ComboboxSelected>>", lambda _e: self.autoload(), add="+")

    # ---- loading ----
    def autoload(self):
        key = (self.app.serial or "", self.scope.get())
        if key[0] and key != self._loaded_for:
            self.reload()

    def reload(self):
        scope = self.scope.get()
        serial = self.app.serial
        self._loaded_for = (serial or "", scope)
        self._generation += 1
        self.app.call(lambda adb, s: apps.list_app_infos(adb, s, scope),
                      self._set_apps, "Reading apps...")

    def _set_apps(self, infos):
        self._rows = {i.package: AppRow(i) for i in infos}
        self._refresh()
        self._start_icons()

    # ---- table ----
    def _sort_by(self, column: str):
        if self._sort[0] == column:
            self._sort = (column, not self._sort[1])
        else:
            self._sort = (column, column in DESCENDING_FIRST)
        self._refresh()

    def _visible(self) -> list[AppRow]:
        text = self.filter.get().strip().lower()
        rows = [r for r in self._rows.values()
                if not text or text in r.package.lower() or text in r.label.lower()]
        column, descending = self._sort
        return sorted(rows, key=SORT_KEYS[column], reverse=descending)

    def _values(self, row: AppRow) -> tuple:
        i = row.info
        return (i.package, human_size(i.total_size), human_size(i.app_size),
                human_size(i.data_size), human_size(i.cache_size), i.installed, i.updated,
                i.installer or ("sideload" if not i.is_system else ""),
                "System" if i.is_system else "User",
                ("Enabled" if i.enabled else "Disabled") + (", running" if i.running else ""))

    def _refresh(self):
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        rows = self._visible()
        for row in rows:
            self.tree.insert("", "end", iid=row.package, text=row.label or row.package,
                             image=row.image or "", values=self._values(row))
        keep = [p for p in selected if self.tree.exists(p)]
        if keep:
            self.tree.selection_set(keep)
        total = sum(r.info.total_size for r in rows)
        self.app.status.set(f"{len(rows)} app(s), {human_size(total)} total")

    # ---- icons and labels (background, progressive) ----
    def _start_icons(self):
        serial = self.app.serial
        if not serial:
            return
        if self._extractor is None:
            self._extractor = IconExtractor(self.app.adb)
        generation = self._generation
        for row in self._rows.values():
            self._pool.submit(self._fetch_icon, serial, generation, row)

    def _fetch_icon(self, serial: str, generation: int, row: AppRow):
        if generation != self._generation or not row.info.apk_path:
            return
        icon = self._extractor.get(serial, row.package, row.info.apk_path)
        try:
            self.after(0, self._apply_icon, generation, row, icon)
        except (tk.TclError, RuntimeError):
            pass

    def _apply_icon(self, generation: int, row: AppRow, icon):
        if generation != self._generation:
            return
        if icon.label:
            row.label = icon.label
        if icon.png_path:
            try:
                row.image = _load_image(icon.png_path)
            except tk.TclError:
                row.image = None
        if self.tree.exists(row.package):
            self.tree.item(row.package, text=row.label or row.package, image=row.image or "")

    # ---- selection ----
    def _selected(self) -> list[str]:
        selection = list(self.tree.selection())
        if not selection:
            messagebox.showinfo("Apps", "Select at least one app.")
        return selection

    # ---- install ----
    def install_file(self):
        path = filedialog.askopenfilename(
            title="Select APK or bundle",
            filetypes=[("Android packages", "*.apk *.apks *.xapk *.zip"), ("All files", "*.*")])
        if path:
            self._install(path)

    def install_folder(self):
        path = filedialog.askdirectory(title="Select folder with split APKs")
        if path:
            self._install(path)

    def _install(self, path):
        def done(result):
            messagebox.showinfo("Install", str(result))
            self.reload()
        self.app.call(lambda adb, serial: apps.install(adb, serial, path), done, "Installing...")

    # ---- per-package actions ----
    def _each(self, packages, func, message):
        def work(adb, serial):
            return [func(adb, serial, p) for p in packages]
        self.app.call(work, lambda _r: self.reload(), message)

    def launch(self):
        for package in self._selected()[:1]:
            self.app.call(lambda adb, s: apps.launch(adb, s, package))

    def force_stop(self):
        packages = self._selected()
        if packages:
            self._each(packages, apps.force_stop, "Stopping...")

    def set_enabled(self, enabled):
        packages = self._selected()
        if packages and (enabled or confirm(
                self, "Disable apps", f"Disable {len(packages)} package(s) for user 0?",
                "adb shell pm disable-user --user 0 <package>")):
            self._each(packages, lambda a, s, p: apps.set_enabled(a, s, p, enabled), "Updating...")

    def clear_data(self):
        packages = self._selected()
        if packages and confirm(self, "Clear data",
                                f"This permanently erases the data of {len(packages)} package(s).",
                                "adb shell pm clear <package>"):
            self._each(packages, apps.clear_data, "Clearing data...")

    def uninstall(self):
        packages = self._selected()
        if not packages:
            return
        keep, system = self.keep_data.get(), self.system_user.get()
        command = ("adb shell pm uninstall " + ("-k " if keep else "") + "--user 0 <package>"
                   if system else "adb uninstall " + ("-k " if keep else "") + "<package>")
        if confirm(self, "Uninstall", f"Uninstall {len(packages)} package(s)?\n" +
                   "\n".join(packages[:10]), command):
            self._each(packages, lambda a, s, p: apps.uninstall(a, s, p, keep, system),
                       "Uninstalling...")

    def extract(self):
        packages = self._selected()
        dest = filedialog.askdirectory(title="Save APKs to...") if packages else ""
        if dest:
            def work(adb, serial):
                return [f for p in packages for f in apps.extract_apk(adb, serial, p, dest)]
            self.app.call(work, lambda files: messagebox.showinfo(
                "Extract APK", f"{len(files)} file(s) saved to {dest}"), "Extracting...")


def _load_image(path: str) -> tk.PhotoImage:
    """Load a PNG scaled down to ICON_PX (integer subsampling, stdlib only)."""
    image = tk.PhotoImage(file=path)
    factor = max(1, -(-max(image.width(), image.height()) // ICON_PX))
    return image.subsample(factor) if factor > 1 else image
