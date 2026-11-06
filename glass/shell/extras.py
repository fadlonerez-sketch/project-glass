"""Small Shell helpers exposed to QML: system load for the Dock widget, and a link to Garvis."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from glass.win.winapi import WNDENUMPROC, user32

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + \
               [(n, ctypes.c_ulonglong) for n in ("total", "avail", "pageTotal", "pageAvail", "virtTotal", "virtAvail", "extAvail")]


def _ft(ft: wintypes.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class SysMon(QObject):
    """CPU and memory load, sampled every 2 s -- only while a System widget is in the Dock."""
    statsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats = {"cpu": 0.0, "mem": 0.0}
        self._prev = None
        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(self._sample)

    @Property("QVariantMap", notify=statsChanged)
    def stats(self):
        return self._stats

    def set_active(self, active: bool) -> None:
        if active and not self._timer.isActive():
            self._sample()
            self._timer.start()
        elif not active:
            self._timer.stop()

    def _sample(self) -> None:
        idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if _kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            cur = (_ft(idle), _ft(kern), _ft(user))
            if self._prev:
                di, dk, du = (c - p for c, p in zip(cur, self._prev))
                total = dk + du
                self._stats["cpu"] = round(max(0.0, min(1.0, (total - di) / total)) if total else 0.0, 3)
            self._prev = cur
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(ms)
        if _kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            self._stats["mem"] = round(ms.dwMemoryLoad / 100, 3)
        self._stats = dict(self._stats)
        self.statsChanged.emit()


GARVIS_PROPERTY = "Garvis.MainWindow"
GARVIS_ACTIVATE = "Garvis.ActivateMainWindow"
user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetPropW.restype = wintypes.HANDLE


class GarvisLink(QObject):
    """Bring Garvis to the front using Garvis's own single-instance protocol, or start it."""
    failed = Signal(str)

    def __init__(self, garvis_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.garvis_dir = garvis_dir or Path(os.environ.get("GARVIS_HOME", Path.home() / "PycharmProjects" / "garvis"))

    def _windows(self) -> list[int]:
        found: list[int] = []

        @WNDENUMPROC
        def cb(hwnd, _):
            if user32.GetPropW(hwnd, GARVIS_PROPERTY):
                found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        return found

    @Slot()
    def activate(self) -> None:
        msg = user32.RegisterWindowMessageW(GARVIS_ACTIVATE)
        wins = self._windows()
        if wins:
            for hwnd in wins:
                user32.PostMessageW(hwnd, msg, 0, 0)
            return
        pyw = self.garvis_dir / ".venv" / "Scripts" / "pythonw.exe"
        script = self.garvis_dir / "run_garvis.py"
        if not (pyw.exists() and script.exists()):
            self.failed.emit("Garvis isn't installed where Glass expects it.")
            return
        subprocess.Popen([str(pyw), str(script)], cwd=str(self.garvis_dir), creationflags=subprocess.DETACHED_PROCESS)


def mark_protected(hwnd: int) -> None:
    """Glass's own windows carry this property; the automation engine refuses to act on them."""
    user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
    user32.SetPropW(hwnd, "ProjectGlass.Protected", 1)
