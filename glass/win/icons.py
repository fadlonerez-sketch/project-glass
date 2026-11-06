"""High-resolution application icons through IShellItemImageFactory (Store logos, exe and shortcut icons)."""
from __future__ import annotations

import ctypes
import hashlib
import logging
import threading
from ctypes import wintypes
from pathlib import Path

import comtypes
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from glass.win import shellcom

log = logging.getLogger(__name__)

_gdi32 = ctypes.WinDLL("gdi32")
_user32 = ctypes.WinDLL("user32")


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

SIIGBF_BIGGERSIZEOK = 0x01
SIIGBF_ICONONLY = 0x04


def _hbitmap_to_qimage(hbm) -> QImage:
    bm = BITMAP()
    _gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, abs(bm.bmHeight)
    hdr = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    hdc = _user32.GetDC(None)
    try:
        _gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(hdr), 0)
    finally:
        _user32.ReleaseDC(None, hdc)
    data = bytes(buf)
    has_alpha = any(data[i] for i in range(3, len(data), 4 * 7))
    fmt = QImage.Format.Format_ARGB32_Premultiplied if has_alpha else QImage.Format.Format_RGB32
    return QImage(data, w, h, w * 4, fmt).copy()


def shell_icon(source: str, size: int) -> QImage | None:
    """Icon for a path, .lnk, exe or shell:AppsFolder\\<id> at (at least) size x size pixels."""
    if not source:
        return None
    shellcom.ensure_com()
    try:
        item = shellcom.item_from_parsing_name(source, shellcom.IShellItem)
        factory = item.QueryInterface(shellcom.IShellItemImageFactory)
        hbm = factory.GetImage(shellcom.SIZE(size, size), SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK)
    except (OSError, comtypes.COMError, ValueError) as exc:
        log.debug("no icon for %s: %s", source, exc)
        return None
    try:
        img = _hbitmap_to_qimage(hbm)
    finally:
        _gdi32.DeleteObject(hbm)
    if img.isNull():
        return None
    if img.width() != size:
        img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


class AppIconProvider(QQuickImageProvider):
    """QML: ``image://appicon/<size>/<source>`` -- loaded asynchronously and cached on disk."""

    def __init__(self, cache_dir: Path):
        super().__init__(QQuickImageProvider.ImageType.Image, QQuickImageProvider.Flag.ForceAsynchronousImageLoading)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, QImage] = {}
        self._lock = threading.Lock()

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:
        from urllib.parse import unquote
        try:
            px_text, source = ident.split("/", 1)
            px = max(16, min(512, int(px_text)))
        except ValueError:
            return QImage()
        source = unquote(source)
        key = hashlib.sha1(f"{source}|{px}".encode("utf-8")).hexdigest()
        with self._lock:
            hit = self._mem.get(key)
        if hit is None:
            path = self._cache_dir / f"{key}.png"
            if path.exists():
                hit = QImage(str(path))
            if hit is None or hit.isNull():
                hit = shell_icon(source, px) or QImage()
                if not hit.isNull():
                    hit.save(str(path), "PNG")
            with self._lock:
                if len(self._mem) > 400:
                    self._mem.clear()
                self._mem[key] = hit
        if size is not None:
            size.setWidth(hit.width())
            size.setHeight(hit.height())
        return hit


class BytesImageProvider(QQuickImageProvider):
    """QML: ``image://<name>/<id>`` for in-memory images (album artwork)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._images: dict[str, QImage] = {}

    def put(self, ident: str, data: bytes) -> None:
        img = QImage.fromData(data)
        if not img.isNull():
            self._images[ident] = img
            for old in list(self._images)[:-4]:
                self._images.pop(old, None)

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:
        img = self._images.get(ident, QImage())
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img
