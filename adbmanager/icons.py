"""App icon and label extraction without aapt.

Only `AndroidManifest.xml` and `resources.arsc` are streamed from the device (`unzip -p`),
then the launcher icon resource is resolved to a PNG inside the APK. Results are cached on disk.
Pillow is optional: with it WebP icons and adaptive icons are converted; without it only
PNG icons are available and everything else falls back to no icon.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import struct
from dataclasses import dataclass

from .adb import Adb, AdbError

try:  # optional
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

ATTR_ICON = 0x01010002
ATTR_LABEL = 0x01010001
ATTR_DRAWABLE = 0x01010199
TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
DENSITY_ANY = 0xFFFE
NO_ENTRY = 0xFFFFFFFF


@dataclass
class AppIcon:
    label: str = ""
    png_path: str = ""


# ---------------------------------------------------------------------------
# Binary parsing helpers
# ---------------------------------------------------------------------------
def parse_string_pool(data: bytes, offset: int) -> list[str]:
    """Parse a ResStringPool chunk starting at `offset`."""
    _type, _hs, _size, count, _styles, flags, strings_start, _ss = struct.unpack_from(
        "<HHIIIIII", data, offset)
    utf8 = bool(flags & (1 << 8))
    offsets = struct.unpack_from(f"<{count}I", data, offset + 28)
    base = offset + strings_start
    result = []
    for off in offsets:
        pos = base + off
        try:
            if utf8:
                length = data[pos]
                pos += 2 if length & 0x80 else 1  # skip char length
                if length & 0x80:
                    pass
                blen = data[pos]
                pos += 1
                if blen & 0x80:
                    blen = ((blen & 0x7F) << 8) | data[pos]
                    pos += 1
                result.append(data[pos:pos + blen].decode("utf-8", "replace"))
            else:
                length = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if length & 0x8000:
                    length = ((length & 0x7FFF) << 16) | struct.unpack_from("<H", data, pos)[0]
                    pos += 2
                result.append(data[pos:pos + length * 2].decode("utf-16-le", "replace"))
        except (IndexError, struct.error):
            result.append("")
    return result


def parse_axml(data: bytes) -> list[tuple[str, dict[str, tuple[int, int, object]]]]:
    """Parse binary XML into [(element_name, {attr_name: (resource_id, type, value)})]."""
    strings: list[str] = []
    res_ids: list[int] = []
    elements = []
    pos = 8
    while pos + 8 <= len(data):
        ctype, hsize, size = struct.unpack_from("<HHI", data, pos)
        if size < 8:
            break
        if ctype == 0x0001:
            strings = parse_string_pool(data, pos)
        elif ctype == 0x0180:
            res_ids = list(struct.unpack_from(f"<{(size - 8) // 4}I", data, pos + 8))
        elif ctype == 0x0102:
            name_idx = struct.unpack_from("<i", data, pos + 20)[0]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, pos + 24)
            attrs = {}
            for i in range(attr_count):
                base = pos + 16 + attr_start + i * attr_size
                _ns, name, raw, _sz, _r0, dtype, value = struct.unpack_from("<iiiHBBI", data, base)
                rid = res_ids[name] if 0 <= name < len(res_ids) else 0
                shown: object = value
                if dtype == TYPE_STRING and 0 <= raw < len(strings):
                    shown = strings[raw]
                key = strings[name] if 0 <= name < len(strings) else str(name)
                attrs[key] = (rid, dtype, shown)
            elements.append((strings[name_idx] if 0 <= name_idx < len(strings) else "", attrs))
        pos += size
    return elements


class ResourceTable:
    """Minimal resources.arsc reader: resource id -> candidate (density, value) entries."""

    def __init__(self, data: bytes):
        self.values: list[str] = []
        self.entries: dict[int, list[tuple[int, bool, int, int]]] = {}
        self._parse(data)

    def _parse(self, data: bytes) -> None:
        pos = struct.unpack_from("<H", data, 2)[0]  # skip table header
        while pos + 8 <= len(data):
            ctype, hsize, size = struct.unpack_from("<HHI", data, pos)
            if size < 8:
                break
            if ctype == 0x0001 and not self.values:
                self.values = parse_string_pool(data, pos)
            elif ctype == 0x0200:
                self._parse_package(data, pos, size, hsize)
            pos += size

    def _parse_package(self, data: bytes, start: int, size: int, hsize: int) -> None:
        package_id = struct.unpack_from("<I", data, start + 8)[0]
        pos = start + hsize
        end = start + size
        while pos + 8 <= end:
            ctype, chsize, csize = struct.unpack_from("<HHI", data, pos)
            if csize < 8:
                break
            if ctype == 0x0201:
                self._parse_type(data, pos, chsize, package_id)
            pos += csize

    def _parse_type(self, data: bytes, start: int, hsize: int, package_id: int) -> None:
        type_id, flags, _res, count, entries_start = struct.unpack_from("<BBHII", data, start + 8)
        density = struct.unpack_from("<H", data, start + 34)[0]
        locale = data[start + 28:start + 30] != b"\x00\x00"
        # (entry index, byte offset) pairs; flags: 0x01 sparse, 0x02 16-bit offsets
        pairs: list[tuple[int, int]] = []
        if flags & 0x01:
            for i, word in enumerate(struct.unpack_from(f"<{count}I", data, start + hsize)):
                pairs.append((word & 0xFFFF, (word >> 16) * 4))
        elif flags & 0x02:
            for i, off16 in enumerate(struct.unpack_from(f"<{count}H", data, start + hsize)):
                if off16 != 0xFFFF:
                    pairs.append((i, off16 * 4))
        else:
            for i, off in enumerate(struct.unpack_from(f"<{count}I", data, start + hsize)):
                if off != NO_ENTRY:
                    pairs.append((i, off))
        for index, off in pairs:
            entry = start + entries_start + off
            esize, eflags, _key = struct.unpack_from("<HHI", data, entry)
            if eflags & 0x0001:  # complex entry (style/array), not a plain value
                continue
            _vsize, _r0, dtype, value = struct.unpack_from("<HBBI", data, entry + 8)
            rid = (package_id << 24) | (type_id << 16) | index
            self.entries.setdefault(rid, []).append((density, locale, dtype, value))

    def resolve(self, rid: int, want_files: bool = True) -> list[tuple[int, int, object]]:
        """Candidates for `rid` as (density, type, value), best first (default locale preferred)."""
        out = []
        for density, locale, dtype, value in self.entries.get(rid, []):
            shown: object = value
            if dtype == TYPE_STRING and 0 <= value < len(self.values):
                shown = self.values[value]
            out.append((locale, density, dtype, shown))
        out.sort(key=lambda c: (c[0], -(0 if c[1] == DENSITY_ANY else c[1])))
        return [(c[1], c[2], c[3]) for c in out]


# ---------------------------------------------------------------------------
# Icon resolution
# ---------------------------------------------------------------------------
def pick_icon_file(table: ResourceTable, rid: int) -> list[str]:
    """Return candidate file paths for a drawable resource, raster files first, dense first."""
    paths = []
    for density, dtype, value in table.resolve(rid):
        if dtype == TYPE_STRING and isinstance(value, str) and value.startswith("res/"):
            paths.append((density, value))
    raster = [p for d, p in sorted(paths, key=lambda x: -(0 if x[0] == DENSITY_ANY else x[0]))
              if p.lower().endswith((".png", ".webp"))]
    xml = [p for d, p in paths if p.lower().endswith(".xml")]
    return raster + xml


def resolve_label(table: ResourceTable | None, attr: tuple[int, int, object] | None) -> str:
    if not attr:
        return ""
    _rid, dtype, value = attr
    if dtype == TYPE_STRING:
        return str(value)
    if dtype == TYPE_REFERENCE and table:
        for _d, t, v in table.resolve(int(value)):
            if t == TYPE_STRING and isinstance(v, str):
                return v
    return ""


class IconExtractor:
    def __init__(self, adb: Adb, cache_dir: str | None = None):
        self.adb = adb
        base = cache_dir or os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache"), "ADBManager", "icons")
        self.cache_dir = base
        os.makedirs(base, exist_ok=True)

    def _key(self, package: str, apk_path: str) -> str:
        return f"{package}-{hashlib.sha1(apk_path.encode()).hexdigest()[:8]}"

    def get(self, serial: str, package: str, apk_path: str) -> AppIcon:
        key = os.path.join(self.cache_dir, self._key(package, apk_path))
        if os.path.isfile(key + ".json"):
            with open(key + ".json", encoding="utf-8") as fh:
                label = json.load(fh).get("label", "")
            return AppIcon(label, key + ".png" if os.path.isfile(key + ".png") else "")
        icon = AppIcon()
        try:
            icon = self._extract(serial, apk_path, key + ".png")
        except (AdbError, struct.error, IndexError, OSError, ValueError):
            pass
        with open(key + ".json", "w", encoding="utf-8") as fh:
            json.dump({"label": icon.label}, fh)
        return icon

    def _unzip(self, serial: str, apk_path: str, member: str) -> bytes:
        command = f"unzip -p {shlex.quote(apk_path)} {shlex.quote(member)}"
        return self.adb.run_bytes(["-s", serial, "exec-out", command], timeout=120)

    def _extract(self, serial: str, apk_path: str, png_out: str) -> AppIcon:
        manifest = parse_axml(self._unzip(serial, apk_path, "AndroidManifest.xml"))
        application = next((a for n, a in manifest if n == "application"), {})
        icon_attr = application.get("icon") or application.get("roundIcon")
        table = ResourceTable(self._unzip(serial, apk_path, "resources.arsc"))
        label = resolve_label(table, application.get("label"))
        if not icon_attr or icon_attr[1] != TYPE_REFERENCE:
            return AppIcon(label)
        data = self._load_drawable(serial, apk_path, table, int(icon_attr[2]), depth=0)
        if not data:
            return AppIcon(label)
        with open(png_out, "wb") as fh:
            fh.write(data)
        return AppIcon(label, png_out)

    def _load_drawable(self, serial: str, apk_path: str, table: ResourceTable, rid: int,
                       depth: int) -> bytes | None:
        """Return PNG bytes for a drawable resource id (follows adaptive icons)."""
        if depth > 3:
            return None
        for path in pick_icon_file(table, rid):
            raw = self._unzip(serial, apk_path, path)
            if path.lower().endswith(".png"):
                return raw
            if path.lower().endswith(".webp"):
                png = _webp_to_png(raw)
                if png:
                    return png
            elif path.lower().endswith(".xml"):
                png = self._adaptive(serial, apk_path, table, raw, depth)
                if png:
                    return png
        return None

    def _adaptive(self, serial: str, apk_path: str, table: ResourceTable, xml: bytes,
                  depth: int) -> bytes | None:
        layers = {}
        for name, attrs in parse_axml(xml):
            if name in ("foreground", "background") and "drawable" in attrs:
                rid, dtype, value = attrs["drawable"]
                if dtype == TYPE_REFERENCE:
                    layers[name] = int(value)
        if "foreground" not in layers:
            return None
        fg = self._load_drawable(serial, apk_path, table, layers["foreground"], depth + 1)
        if fg is None:
            return None
        bg = (self._load_drawable(serial, apk_path, table, layers["background"], depth + 1)
              if "background" in layers else None)
        return _compose(fg, bg)


def _webp_to_png(raw: bytes) -> bytes | None:
    if Image is None:
        return None
    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGBA").save(out, "PNG")
    return out.getvalue()


def _compose(foreground: bytes, background: bytes | None) -> bytes:
    """Stack adaptive icon layers when Pillow is available; otherwise use the foreground."""
    if Image is None:
        return foreground
    fg = Image.open(io.BytesIO(foreground)).convert("RGBA")
    canvas = Image.new("RGBA", fg.size, (0, 0, 0, 0))
    if background:
        canvas.alpha_composite(Image.open(io.BytesIO(background)).convert("RGBA").resize(fg.size))
    canvas.alpha_composite(fg)
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()
