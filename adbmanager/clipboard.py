"""Copy PNG images to the Windows clipboard using only ctypes. No GUI imports."""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_CF_DIB = 8
_GMEM_MOVEABLE = 0x0002
_OPAQUE_WHITE = 0xFFFFFFFF


class ClipboardError(Exception):
    pass


class _Bitmap(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG),
                ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD),
                ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _GdiplusStartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32),
                ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", wintypes.BOOL),
                ("SuppressExternalCodecs", wintypes.BOOL)]


def _load(name: str, prototypes: dict):
    """Load a private DLL handle and declare the signatures, required for 64-bit handles."""
    dll = ctypes.WinDLL(name, use_last_error=True)
    for function, (restype, argtypes) in prototypes.items():
        getattr(dll, function).restype = restype
        getattr(dll, function).argtypes = argtypes
    return dll


def _png_to_hbitmap(data: bytes) -> int:
    """Decode a PNG with GDI+ and return a GDI bitmap handle owned by the caller."""
    pointer = ctypes.POINTER(ctypes.c_void_p)
    gdiplus = _load("gdiplus", {
        "GdiplusStartup": (ctypes.c_int, [ctypes.POINTER(ctypes.c_size_t),
                                          ctypes.POINTER(_GdiplusStartupInput),
                                          ctypes.c_void_p]),
        "GdiplusShutdown": (None, [ctypes.c_size_t]),
        "GdipCreateBitmapFromFile": (ctypes.c_int, [wintypes.LPCWSTR, pointer]),
        "GdipCreateHBITMAPFromBitmap": (ctypes.c_int, [ctypes.c_void_p, pointer,
                                                       wintypes.DWORD]),
        "GdipDisposeImage": (ctypes.c_int, [ctypes.c_void_p]),
    })
    token = ctypes.c_size_t()
    startup = _GdiplusStartupInput(1, None, False, False)
    if gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None):
        raise ClipboardError("Could not initialize GDI+.")
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "image.png")
            with open(path, "wb") as handle:
                handle.write(data)
            image, bitmap = ctypes.c_void_p(), ctypes.c_void_p()
            if gdiplus.GdipCreateBitmapFromFile(path, ctypes.byref(image)):
                raise ClipboardError("Could not decode the image.")
            try:
                if gdiplus.GdipCreateHBITMAPFromBitmap(image, ctypes.byref(bitmap),
                                                       _OPAQUE_WHITE):
                    raise ClipboardError("Could not convert the image to a bitmap.")
            finally:
                gdiplus.GdipDisposeImage(image)  # releases the lock on the file
            return bitmap.value
    finally:
        gdiplus.GdiplusShutdown(token)


def _png_to_dib(data: bytes) -> bytes:
    """Convert a PNG to a packed 32-bit device independent bitmap (header plus pixels)."""
    gdi32 = _load("gdi32", {
        "GetObjectW": (ctypes.c_int, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]),
        "GetDIBits": (ctypes.c_int, [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                     wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.UINT]),
        "DeleteObject": (wintypes.BOOL, [wintypes.HANDLE]),
    })
    user32 = _load("user32", {
        "GetDC": (wintypes.HDC, [wintypes.HWND]),
        "ReleaseDC": (ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
    })
    bitmap = _png_to_hbitmap(data)
    try:
        size = _Bitmap()
        if not gdi32.GetObjectW(bitmap, ctypes.sizeof(size), ctypes.byref(size)):
            raise ClipboardError("Could not read the bitmap.")
        header = _BitmapInfoHeader(biSize=ctypes.sizeof(_BitmapInfoHeader),
                                   biWidth=size.bmWidth, biHeight=size.bmHeight,
                                   biPlanes=1, biBitCount=32,
                                   biSizeImage=size.bmWidth * size.bmHeight * 4)
        pixels = ctypes.create_string_buffer(header.biSizeImage)
        context = user32.GetDC(None)
        try:
            lines = gdi32.GetDIBits(context, bitmap, 0, size.bmHeight, pixels,
                                    ctypes.byref(header), 0)
        finally:
            user32.ReleaseDC(None, context)
        if lines != size.bmHeight:
            raise ClipboardError("Could not read the bitmap pixels.")
        return bytes(header) + pixels.raw
    finally:
        gdi32.DeleteObject(bitmap)


def copy_png(data: bytes) -> None:
    """Put a PNG image on the clipboard, both as a bitmap and in the "PNG" format."""
    if not data.startswith(PNG_SIGNATURE):
        raise ClipboardError("The data is not a PNG image.")
    if sys.platform != "win32":
        raise ClipboardError("Copying images to the clipboard is only supported on Windows.")

    user32 = _load("user32", {
        "OpenClipboard": (wintypes.BOOL, [wintypes.HWND]),
        "EmptyClipboard": (wintypes.BOOL, []),
        "CloseClipboard": (wintypes.BOOL, []),
        "SetClipboardData": (wintypes.HANDLE, [wintypes.UINT, wintypes.HANDLE]),
        "RegisterClipboardFormatW": (wintypes.UINT, [wintypes.LPCWSTR]),
    })
    kernel32 = _load("kernel32", {
        "GlobalAlloc": (wintypes.HGLOBAL, [wintypes.UINT, ctypes.c_size_t]),
        "GlobalLock": (ctypes.c_void_p, [wintypes.HGLOBAL]),
        "GlobalUnlock": (wintypes.BOOL, [wintypes.HGLOBAL]),
        "GlobalFree": (wintypes.HGLOBAL, [wintypes.HGLOBAL]),
    })

    def put(clipboard_format: int, content: bytes) -> bool:
        memory = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(content))
        if not memory:
            return False
        target = kernel32.GlobalLock(memory)
        if target:
            ctypes.memmove(target, content, len(content))
            kernel32.GlobalUnlock(memory)
            # Once accepted, the memory belongs to the system and must not be freed.
            if user32.SetClipboardData(clipboard_format, memory):
                return True
        kernel32.GlobalFree(memory)
        return False

    dib = _png_to_dib(data)
    for _ in range(10):  # another process may be holding the clipboard
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise ClipboardError("The clipboard is in use by another application.")
    try:
        user32.EmptyClipboard()
        if not put(_CF_DIB, dib):
            raise ClipboardError("Could not copy the image to the clipboard.")
        # Optional lossless copy, preferred by browsers and some editors.
        put(user32.RegisterClipboardFormatW("PNG"), data)
    finally:
        user32.CloseClipboard()
