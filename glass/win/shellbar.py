"""Desktop space reservation (AppBars), the reversible Windows-taskbar controller, and global hotkeys.

All three use documented APIs:

* ``SHAppBarMessage`` -- registering the top bar and the Dock as application desktop toolbars reserves
  their strip of the work area, so maximised windows stop short of them; Windows also tells us when a
  full-screen app takes over (ABN_FULLSCREENAPP) so Glass steps aside.
* The taskbar is hidden reversibly: its auto-hide state (``ABM_SETSTATE``, the same switch as Taskbar
  settings) frees its strip, and its windows are hidden with ``ShowWindow``. The original state is saved
  in ``recovery-state.json`` *before* anything changes, and the watchdog restores it if Glass dies.
* ``RegisterHotKey`` for the recovery and emergency-stop shortcuts.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import time
from ctypes import wintypes
from pathlib import Path

from glass.win.winapi import (RECT, SW_HIDE, SW_SHOWNA, WINEVENTPROC, EVENT_OBJECT_SHOW, WINEVENT_OUTOFCONTEXT,
                              user32, window_pid)

log = logging.getLogger(__name__)

_shell32 = ctypes.WinDLL("shell32")


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", RECT), ("lParam", wintypes.LPARAM)]


_shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
_shell32.SHAppBarMessage.restype = ctypes.c_size_t

ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS, ABM_GETSTATE = 0, 1, 2, 3, 4
ABM_ACTIVATE, ABM_WINDOWPOSCHANGED, ABM_SETSTATE = 6, 9, 10
ABN_STATECHANGE, ABN_POSCHANGED, ABN_FULLSCREENAPP = 0, 1, 2
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
ABS_AUTOHIDE, ABS_ALWAYSONTOP = 1, 2

APPBAR_CALLBACK = user32.RegisterWindowMessageW("ProjectGlass.AppBar")
TASKBAR_CREATED = user32.RegisterWindowMessageW("TaskbarCreated")


def _abd(hwnd: int = 0) -> APPBARDATA:
    d = APPBARDATA()
    d.cbSize = ctypes.sizeof(APPBARDATA)
    d.hWnd = hwnd
    return d


class AppBar:
    """Reserve ``thickness`` physical pixels along ``edge`` of the monitor ``monitor_rect`` for ``hwnd``."""

    def __init__(self, hwnd: int, edge: int):
        self.hwnd = hwnd
        self.edge = edge
        self.registered = False
        self.rect: tuple[int, int, int, int] | None = None
        self._last = None

    def register(self) -> bool:
        d = _abd(self.hwnd)
        d.uCallbackMessage = APPBAR_CALLBACK
        self.registered = bool(_shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(d)))
        if not self.registered:
            log.warning("ABM_NEW failed for %#x", self.hwnd)
        return self.registered

    def set_position(self, monitor_rect: tuple[int, int, int, int], thickness: int) -> tuple[int, int, int, int] | None:
        """Returns the rectangle Windows granted (it may be pushed inward by other app bars)."""
        if not self.registered:
            return None
        self._last = (monitor_rect, thickness)
        x, y, w, h = monitor_rect
        d = _abd(self.hwnd)
        d.uEdge = self.edge
        d.rc = RECT(x, y, x + w, y + h)
        if self.edge == ABE_TOP:
            d.rc.bottom = y + thickness
        elif self.edge == ABE_BOTTOM:
            d.rc.top = y + h - thickness
        elif self.edge == ABE_LEFT:
            d.rc.right = x + thickness
        else:
            d.rc.left = x + w - thickness
        _shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(d))
        if self.edge == ABE_TOP:
            d.rc.bottom = d.rc.top + thickness
        elif self.edge == ABE_BOTTOM:
            d.rc.top = d.rc.bottom - thickness
        elif self.edge == ABE_LEFT:
            d.rc.right = d.rc.left + thickness
        else:
            d.rc.left = d.rc.right - thickness
        _shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(d))
        self.rect = d.rc.tuple()
        return self.rect

    def reapply(self) -> None:
        if self._last:
            self.set_position(*self._last)

    def window_pos_changed(self) -> None:
        if self.registered:
            _shell32.SHAppBarMessage(ABM_WINDOWPOSCHANGED, ctypes.byref(_abd(self.hwnd)))

    def activate(self) -> None:
        if self.registered:
            _shell32.SHAppBarMessage(ABM_ACTIVATE, ctypes.byref(_abd(self.hwnd)))

    def unregister(self) -> None:
        if self.registered:
            _shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(_abd(self.hwnd)))
            self.registered = False


# --------------------------------------------------------------------------------------------- taskbar

def taskbar_windows() -> list[int]:
    out = []
    primary = user32.FindWindowW("Shell_TrayWnd", None)
    if primary:
        out.append(primary)
    child = None
    while True:
        child = user32.FindWindowExW(None, child, "Shell_SecondaryTrayWnd", None)
        if not child:
            break
        out.append(child)
    return out


def get_taskbar_state() -> int:
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    return int(_shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(_abd(tray or 0))))


def set_taskbar_state(state: int) -> None:
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    d = _abd(tray or 0)
    d.lParam = state
    _shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(d))


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def restore_taskbar_from_state(path: Path) -> bool:
    """Undo whatever Glass did to the taskbar, using the state saved before it changed anything.

    Safe to call at any time and from any process (the watchdog and the 'Restore Windows Desktop'
    command use it). Returns True if something was restored."""
    st = read_state(path)
    if not st.get("taskbar_hidden"):
        for hwnd in taskbar_windows():  # still make sure it's visible
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_SHOWNA)
        return False
    original = int(st.get("taskbar_original_state", 0))
    set_taskbar_state(original)
    for hwnd in taskbar_windows():
        user32.ShowWindow(hwnd, SW_SHOWNA)
    st.update(taskbar_hidden=False, restored_at=time.time())
    write_state(path, st)
    log.info("Windows taskbar restored (state %d)", original)
    return True


class TaskbarController:
    """Hides the Windows taskbar while Glass runs; everything is reversible and recorded first."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.hidden = False
        self._revealing_until = 0.0
        self._hook = None
        self._cb = WINEVENTPROC(self._on_show)

    def hide(self) -> None:
        st = read_state(self.state_path)
        if not st.get("taskbar_hidden"):
            # Record the user's own setting before touching anything (never overwrite a saved original).
            st["taskbar_original_state"] = get_taskbar_state()
        st.update(taskbar_hidden=True, shell_pid=os.getpid(), hidden_at=time.time())
        write_state(self.state_path, st)
        original = int(st["taskbar_original_state"])
        set_taskbar_state((original & ABS_ALWAYSONTOP) | ABS_AUTOHIDE)
        self.hidden = True
        self._apply_hidden()
        self._watch()

    def _apply_hidden(self) -> None:
        for hwnd in taskbar_windows():
            if user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_HIDE)

    def _watch(self) -> None:
        if self._hook:
            return
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        pid = window_pid(tray) if tray else 0
        if pid:
            self._hook = user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, self._cb, pid, 0,
                                                WINEVENT_OUTOFCONTEXT)

    def _on_show(self, hook, event, hwnd, obj, child, thread, t):
        if obj != 0 or not self.hidden or time.monotonic() < self._revealing_until:
            return
        if hwnd in taskbar_windows():
            user32.ShowWindow(hwnd, SW_HIDE)

    def reveal(self, seconds: float = 10.0) -> None:
        """Compatibility route for tray icons Glass can't mirror: show the real taskbar for a moment."""
        self._revealing_until = time.monotonic() + seconds
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if tray:
            user32.ShowWindow(tray, SW_SHOWNA)
            user32.SetForegroundWindow(tray)

    def end_reveal(self) -> None:
        self._revealing_until = 0.0
        if self.hidden:
            self._apply_hidden()

    def explorer_restarted(self) -> None:
        """TaskbarCreated: Explorer came back; unhook the old process and hide the new taskbar."""
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        if self.hidden:
            self._apply_hidden()
            self._watch()

    def restore(self) -> None:
        if self._hook:
            user32.UnhookWinEvent(self._hook)
            self._hook = None
        self.hidden = False
        restore_taskbar_from_state(self.state_path)


# --------------------------------------------------------------------------------------------- hotkeys

MOD = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
VK_NAMES = {"esc": 0x1B, "escape": 0x1B, "space": 0x20, "end": 0x23, "home": 0x24, "pause": 0x13,
            "delete": 0x2E, "insert": 0x2D, "f1": 0x70}
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def parse_hotkey(text: str) -> tuple[int, int]:
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty shortcut")
    mods = 0
    for p in parts[:-1]:
        if p not in MOD:
            raise ValueError(f"unknown modifier {p}")
        mods |= MOD[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in VK_NAMES:
        vk = VK_NAMES[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        raise ValueError(f"unknown key {key}")
    return mods, vk


class GlobalHotkeys:
    """Thread-level RegisterHotKey; the owner feeds WM_HOTKEY messages from its native event filter."""

    def __init__(self):
        self._ids: dict[int, callable] = {}
        self._next = 0x6A00

    def register(self, text: str, callback) -> bool:
        mods, vk = parse_hotkey(text)
        hid = self._next
        self._next += 1
        if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
            log.warning("hotkey %s is taken by another program", text)
            return False
        self._ids[hid] = callback
        return True

    def handle(self, msg_id: int, wparam: int) -> bool:
        if msg_id == WM_HOTKEY and wparam in self._ids:
            self._ids[wparam]()
            return True
        return False

    def unregister_all(self) -> None:
        for hid in list(self._ids):
            user32.UnregisterHotKey(None, hid)
        self._ids.clear()
