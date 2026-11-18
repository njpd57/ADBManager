# ADBManager

Android device manager over adb (Python + Tkinter, no external dependencies). Sibling of ADBFinder.

## Requirements
- Python 3.9+
- `adb` (platform-tools), found in `PATH`, `C:\platform-tools` or `ADB_PATH`. `fastboot` is optional (`FASTBOOT_PATH`).
- Device with **USB debugging** enabled and authorized.

## Usage
```
python main.py
```
Pick a device at the top, then use the tabs:

| Tab | What it does |
|---|---|
| Device | Wi-Fi connect/pair/disconnect, enable TCP/IP, device info |
| Apps | Sortable table with icon, real name, sizes (total/app/data/cache), install/update dates, installer, type and state (enabled/running); install APK / split folder / XAPK, uninstall, disable/enable, clear data, force-stop, launch, extract APK |
| Capture | Screenshot and screen recording (pulled to the PC) |
| Shell & Logcat | One-shot shell with history, live logcat with level/tag/text filters, reboot (normal/recovery/bootloader/fastbootd/sideload) |
| System | Live monitor (battery, RAM, network, top), processes, system properties |
| Backup & Permissions | `adb backup`/`restore`, runtime permissions grant/revoke, sideload, basic fastboot |
| Log & Console | History of every executed adb command and a raw adb console |

Icons and names are read from the APK (only the manifest and resources are streamed, cached under `%LOCALAPPDATA%\ADBManager\icons`). PNG icons need no extra packages; Pillow is optional and adds WebP/adaptive icons. Apps whose icon is a vector drawable show no icon.

Destructive actions always ask for confirmation and show the exact command.

## Tests
```
python -m unittest discover tests
```

## Package
```
pip install pyinstaller
pyinstaller --noconsole --onefile main.py
```
