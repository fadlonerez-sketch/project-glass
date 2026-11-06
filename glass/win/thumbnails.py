"""Live window thumbnails for the Dock's window previews, via the documented DWM thumbnail API.

DwmRegisterThumbnail asks the compositor to draw a live view of another window inside one of ours. No pixel
ever reaches this process: there is nothing to save, send or leak, and nothing here is reachable by Garvis
(the automation engine is a separate process with no access to the Shell's windows). Thumbnails update by
themselves inside DWM, so there is no polling, and they cost nothing once registered.

Thumbnails are drawn by DWM above our own content, in device pixels relative to the destination window's
client area. ``ThumbnailHost`` keeps the set registered for one destination window in sync with the
rectangles QML asks for, fades them in, and unregisters them as soon as they are not needed or their source
window is gone.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

DWM_TNP_RECTDESTINATION = 0x1
DWM_TNP_RECTSOURCE = 0x2
DWM_TNP_OPACITY = 0x4
DWM_TNP_VISIBLE = 0x8
DWM_TNP_SOURCECLIENTAREAONLY = 0x10
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [("dwFlags", wintypes.DWORD), ("rcDestination", wintypes.RECT), ("rcSource", wintypes.RECT),
                ("opacity", ctypes.c_ubyte), ("fVisible", wintypes.BOOL), ("fSourceClientAreaOnly", wintypes.BOOL)]


class _Api:
    """Thin ctypes binding; replaceable in tests."""

    def __init__(self):
        self.dwm = ctypes.WinDLL("dwmapi")
        self.user32 = ctypes.WinDLL("user32")
        self.dwm.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)]
        self.dwm.DwmRegisterThumbnail.restype = ctypes.c_long
        self.dwm.DwmUnregisterThumbnail.argtypes = [ctypes.c_void_p]
        self.dwm.DwmUnregisterThumbnail.restype = ctypes.c_long
        self.dwm.DwmUpdateThumbnailProperties.argtypes = [ctypes.c_void_p, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
        self.dwm.DwmUpdateThumbnailProperties.restype = ctypes.c_long
        self.dwm.DwmQueryThumbnailSourceSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.SIZE)]
        self.dwm.DwmQueryThumbnailSourceSize.restype = ctypes.c_long
        self.dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsIconic.argtypes = [wintypes.HWND]

    def register(self, dest: int, src: int) -> int:
        h = ctypes.c_void_p()
        hr = self.dwm.DwmRegisterThumbnail(dest, src, ctypes.byref(h))
        return (h.value or 0) if hr == 0 else 0

    def unregister(self, thumb: int) -> None:
        self.dwm.DwmUnregisterThumbnail(ctypes.c_void_p(thumb))

    def update(self, thumb: int, rect: tuple[int, int, int, int], opacity: int, visible: bool) -> bool:
        p = DWM_THUMBNAIL_PROPERTIES()
        p.dwFlags = DWM_TNP_RECTDESTINATION | DWM_TNP_OPACITY | DWM_TNP_VISIBLE | DWM_TNP_SOURCECLIENTAREAONLY
        p.rcDestination = wintypes.RECT(*rect)
        p.opacity = max(0, min(255, int(opacity)))
        p.fVisible = bool(visible)
        p.fSourceClientAreaOnly = False
        return self.dwm.DwmUpdateThumbnailProperties(ctypes.c_void_p(thumb), ctypes.byref(p)) == 0

    def source_size(self, thumb: int) -> tuple[int, int]:
        sz = wintypes.SIZE()
        if self.dwm.DwmQueryThumbnailSourceSize(ctypes.c_void_p(thumb), ctypes.byref(sz)) == 0:
            return sz.cx, sz.cy
        return 0, 0

    def is_window(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindow(hwnd))

    def frame_size(self, hwnd: int) -> tuple[int, int]:
        """The visible frame (without the invisible resize borders), in physical px."""
        r = wintypes.RECT()
        if self.dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) == 0:
            return max(0, r.right - r.left), max(0, r.bottom - r.top)
        return 0, 0

    def cloaked(self, hwnd: int) -> bool:
        v = wintypes.DWORD()
        return self.dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)) == 0 and v.value != 0

    def minimized(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(hwnd))


def fit(src_w: float, src_h: float, box_w: float, box_h: float) -> tuple[float, float, float, float]:
    """Aspect-fit a source of src_w x src_h into a box, centred. Returns (x, y, w, h) within the box."""
    if src_w <= 0 or src_h <= 0 or box_w <= 0 or box_h <= 0:
        return 0.0, 0.0, 0.0, 0.0
    s = min(box_w / src_w, box_h / src_h)
    w, h = src_w * s, src_h * s
    return (box_w - w) / 2, (box_h - h) / 2, w, h


def to_device(rect: tuple[float, float, float, float], dpr: float) -> tuple[int, int, int, int]:
    """A logical (x, y, w, h) rectangle to a device-pixel RECT (left, top, right, bottom), snapped outward-in so
    neighbouring thumbnails never overlap by rounding."""
    x, y, w, h = rect
    return (int(round(x * dpr)), int(round(y * dpr)), int(round((x + w) * dpr)), int(round((y + h) * dpr)))


@dataclass
class _Thumb:
    handle: int
    rect: tuple[int, int, int, int]
    opacity: int
    target_opacity: int


class ThumbnailHost:
    """The live thumbnails shown in one destination window."""

    FADE_STEPS = 6

    def __init__(self, dest_hwnd: int, api: _Api | None = None):
        self.dest = dest_hwnd
        self.api = api or _Api()
        self.thumbs: dict[int, _Thumb] = {}      # source hwnd -> thumbnail

    def available(self, src: int) -> str:
        """Why a window can't have a live thumbnail ("" if it can): the card then shows its fallback."""
        if not self.api.is_window(src):
            return "gone"
        if self.api.minimized(src):
            return "minimized"
        if self.api.cloaked(src):
            return "elsewhere"     # on another virtual desktop
        return ""

    def show(self, items: list[dict], dpr: float) -> dict[int, str]:
        """Show exactly these thumbnails. ``items``: [{hwnd, x, y, w, h}] in logical px of the destination's
        client area (the card's thumbnail box; the image is aspect-fitted inside). Returns, per hwnd, "" if a
        live thumbnail is shown or the reason it is not."""
        wanted: dict[int, tuple[int, int, int, int]] = {}
        status: dict[int, str] = {}
        for it in items:
            src = int(it["hwnd"])
            reason = self.available(src)
            if reason:
                status[src] = reason
                continue
            fw, fh = self.api.frame_size(src)
            fx, fy, w, h = fit(fw or 16, fh or 9, float(it["w"]), float(it["h"]))
            wanted[src] = to_device((float(it["x"]) + fx, float(it["y"]) + fy, w, h), dpr)
        for src in list(self.thumbs):
            if src not in wanted:
                self._drop(src)
        for src, rect in wanted.items():
            t = self.thumbs.get(src)
            if t is None:
                handle = self.api.register(self.dest, src)
                if not handle:
                    status[src] = "unsupported"
                    continue
                t = self.thumbs[src] = _Thumb(handle, rect, 0, 255)
            t.rect, t.target_opacity = rect, 255
            if not self.api.update(t.handle, t.rect, t.opacity, True):
                self._drop(src)
                status[src] = "unsupported"
                continue
            status[src] = ""
        return status

    def fade_step(self) -> bool:
        """Advance every fade by one step. Returns True while any fade is still running."""
        running = False
        step = max(1, 255 // self.FADE_STEPS + 1)
        for src, t in list(self.thumbs.items()):
            if t.opacity == t.target_opacity:
                continue
            t.opacity = min(t.target_opacity, t.opacity + step) if t.opacity < t.target_opacity else max(t.target_opacity, t.opacity - step)
            if not self.api.update(t.handle, t.rect, t.opacity, t.opacity > 0):
                self._drop(src)
                continue
            running = running or t.opacity != t.target_opacity
        return running

    def hide_all(self) -> None:
        """Make every thumbnail invisible at once (the preview is moving or closing)."""
        for src, t in list(self.thumbs.items()):
            t.opacity = 0
            if not self.api.update(t.handle, t.rect, 0, False):
                self._drop(src)

    def prune(self) -> list[int]:
        """Unregister thumbnails whose source window no longer exists."""
        gone = [src for src in self.thumbs if not self.api.is_window(src)]
        for src in gone:
            self._drop(src)
        return gone

    def clear(self) -> None:
        for src in list(self.thumbs):
            self._drop(src)

    def _drop(self, src: int) -> None:
        t = self.thumbs.pop(src, None)
        if t is not None:
            try:
                self.api.unregister(t.handle)
            except OSError:
                log.debug("unregister failed for %s", src)
