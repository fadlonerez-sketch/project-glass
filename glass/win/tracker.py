"""Event-driven window tracker (no polling).

Out-of-context WinEvent hooks (no code injected anywhere) on the GUI thread's message loop report window
creation, destruction, show/hide, title changes, foreground changes, minimise/restore and cloaking (which
is how Windows moves windows between virtual desktops). Bursts are coalesced into one rescan.

Rescans run on a worker thread. A scan asks other processes for window properties and asks Explorer about
virtual desktops; when one of them is busy that can take hundreds of milliseconds, and it must never stall
the UI thread that animates the Dock and the Dynamic Glass.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from glass.win import appwin, shellcom
from glass.win.winapi import (EVENT_OBJECT_CLOAKED, EVENT_OBJECT_CREATE, EVENT_OBJECT_HIDE,
                              EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_SHOW, EVENT_OBJECT_UNCLOAKED,
                              EVENT_SYSTEM_DESKTOPSWITCH, EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND,
                              EVENT_SYSTEM_MINIMIZESTART, OBJID_WINDOW, WINEVENT_OUTOFCONTEXT,
                              WINEVENT_SKIPOWNPROCESS, WINEVENTPROC, kernel32, user32)

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4


def process_start_time(pid: int) -> float:
    """Process creation time as a Unix timestamp (0 if unavailable)."""
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return 0.0
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not _kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return 0.0
        ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
        return ticks / 10_000_000 - 11644473600
    finally:
        kernel32.CloseHandle(h)


@dataclass(frozen=True)
class TrackedWindow:
    info: appwin.WindowInfo
    on_current_desktop: bool
    desktop_id: str
    started: float          # process creation time


@dataclass(frozen=True)
class Snapshot:
    windows: tuple[TrackedWindow, ...]
    foreground: int
    taken: float


class WindowTracker(QObject):
    changed = Signal(object)           # Snapshot
    foregroundChanged = Signal(int)
    _scanned = Signal(object)          # worker -> UI thread

    def __init__(self, parent=None, exclude_pids: set[int] | None = None, offscreen_limit: int = -20000):
        super().__init__(parent)
        self._exclude = set(exclude_pids or set()) | {os.getpid()}
        self._offscreen = offscreen_limit
        self._hooks: list[int] = []
        self._cb = WINEVENTPROC(self._on_event)
        self._debounce = QTimer(self, singleShot=True, interval=40)
        self._debounce.timeout.connect(self.request_rescan)
        self._pool: ThreadPoolExecutor | None = None
        self._local = threading.local()
        self._busy = False
        self._dirty = False
        self._scanned.connect(self._on_scanned)
        self._vd = shellcom.VirtualDesktops()
        self._garvis_desktops: set[str] = set()
        self.snapshot: Snapshot | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        names = self._vd.names()
        self._garvis_desktops = {k for k, v in names.items() if v.strip().lower() == "garvis"}
        ranges = [(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND), (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
                  (EVENT_SYSTEM_DESKTOPSWITCH, EVENT_SYSTEM_DESKTOPSWITCH),
                  (EVENT_OBJECT_CREATE, EVENT_OBJECT_HIDE), (EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE),
                  (EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED)]
        for lo, hi in ranges:
            h = user32.SetWinEventHook(lo, hi, None, self._cb, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
            if h:
                self._hooks.append(h)
            else:
                log.warning("SetWinEventHook(%#x) failed", lo)
        self.rescan()

    def stop(self) -> None:
        for h in self._hooks:
            user32.UnhookWinEvent(h)
        self._hooks.clear()
        self._debounce.stop()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def add_excluded_pid(self, pid: int) -> None:
        self._exclude.add(pid)

    def garvis_desktops(self) -> set[str]:
        return set(self._garvis_desktops)

    # ------------------------------------------------------------------ events
    def _on_event(self, hook, event, hwnd, id_object, id_child, thread, time_ms):
        if id_object != OBJID_WINDOW or id_child != 0 or not hwnd:
            return
        if event == EVENT_SYSTEM_FOREGROUND:
            self.foregroundChanged.emit(int(hwnd))
        elif event in (EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE, EVENT_OBJECT_NAMECHANGE):
            # Only top-level windows matter; child controls churn constantly. (A destroyed window can't be
            # inspected any more, so DESTROY always triggers a rescan.)
            root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
            if root and root != hwnd:
                return
        if not self._debounce.isActive():
            self._debounce.start()

    def request_rescan(self) -> None:
        """Rescan on the worker thread; requests made while one runs are folded into one follow-up scan."""
        if self._busy:
            self._dirty = True
            return
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="glass-windows")
        self._busy = True
        self._pool.submit(self._scan_on_worker)

    def _scan_on_worker(self) -> None:
        try:
            vd = getattr(self._local, "vd", None)
            if vd is None:
                shellcom.ensure_com()
                vd = self._local.vd = shellcom.VirtualDesktops()
            snap = self._collect(vd)
        except Exception:
            log.exception("window rescan failed")
            snap = None
        self._scanned.emit(snap)

    def _on_scanned(self, snap) -> None:
        self._busy = False
        if snap is not None:
            self.snapshot = snap
            self.changed.emit(snap)
        if self._dirty:
            self._dirty = False
            self.request_rescan()

    def rescan(self) -> None:
        """Synchronous rescan on the calling (UI) thread: startup and tests."""
        self.snapshot = self._collect(self._vd)
        self.changed.emit(self.snapshot)

    def _collect(self, vd) -> Snapshot:
        start = time.perf_counter()
        fg = int(user32.GetForegroundWindow() or 0)
        out: list[TrackedWindow] = []
        for hwnd in appwin.top_level_windows():
            try:
                if not appwin.is_app_window(hwnd):
                    continue
                info = appwin.window_info(hwnd)
            except OSError:
                continue
            if info.pid in self._exclude or info.exe_name in appwin.NEVER_APPS:
                continue
            x, y, w, h = info.rect
            if not info.minimized and (x <= self._offscreen or y <= self._offscreen):
                continue  # parked off-screen automation windows (Garvis research browser, test targets)
            desk = vd.desktop_id(hwnd)
            out.append(TrackedWindow(info=info, on_current_desktop=vd.on_current(hwnd), desktop_id=desk,
                                     started=process_start_time(info.pid)))
        snap = Snapshot(tuple(out), fg, time.time())
        elapsed = (time.perf_counter() - start) * 1000
        if elapsed > 150:
            log.info("window rescan took %.1f ms for %d windows (off the UI thread)", elapsed, len(out))
        return snap
