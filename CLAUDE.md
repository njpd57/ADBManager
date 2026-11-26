# ADBManager

Tkinter app that manages Android devices through adb. Standard library only.

## Layout
- `adbmanager/adb.py`: `Adb` runner (logs every command to listeners), device discovery. No GUI imports.
- `adbmanager/{devices,apps,capture,shell,system,backup}.py`: logic per module, pure functions taking `(adb, serial, ...)`; parsers are separate functions so they can be unit tested.
- `adbmanager/icons.py`: aapt-free icon/label extraction (binary XML + resources.arsc parsers, disk cache). Pillow optional.
- `adbmanager/tabs/`: one Tk tab per module. Tabs run work through `App.call(func, on_done)` (background thread, errors shown in a dialog).
- `adbmanager/ui.py`: `run_bg`, `confirm`, `TextView`.

## Rules
- All code, comments and messages in English.
- Destructive actions must go through `ui.confirm` showing the exact command.
- Add parsers with a unit test in `tests/test_parsers.py`; run `python -m unittest discover tests`.
- No Claude attribution in commits, PRs or releases.
- Backlog: Files tab (ADBFinder), input/control (tap, text, intents, DPI, toggles), scrcpy mirroring.
