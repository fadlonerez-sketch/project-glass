"""Synthetic input -- used ONLY for the explicit `input` scope (`click`, `type_text`, `input.keys`) and
for `window.focus`. Semantic UI Automation actions never come through here.

`RealInput` uses SendInput/SetForegroundWindow. `FakeInput` (engine flag `--fake-input`) records the
calls instead; tests use it so they never inject input into the user's session or steal focus.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "cmd": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "menu": 0x5D, "apps": 0x5D,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{chr(c): c for c in range(ord("0"), ord("9") + 1)},
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE,
}
MODIFIERS = {"ctrl", "control", "shift", "alt", "win", "cmd"}
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B, 0x5D}


def parse_keys(spec: str) -> list[list[int]]:
    """'ctrl+s' -> [[CTRL, S]]; 'ctrl+a, delete' -> two chords. Raises ValueError on unknown keys."""
    chords: list[list[int]] = []
    for chord in [c.strip() for c in spec.replace(";", ",").split(",") if c.strip()]:
        names = [k.strip().lower() for k in chord.split("+") if k.strip()]
        if not names:
            continue
        codes = []
        for n in names:
            if n not in VK:
                raise ValueError(f"unknown key '{n}'")
            codes.append(VK[n])
        chords.append(codes)
    if not chords:
        raise ValueError("no keys given")
    return chords


class InputBackend:
    def focus(self, hwnd: int) -> bool: ...
    def keys(self, chords: list[list[int]]) -> None: ...
    def text(self, text: str) -> None: ...
    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None: ...
    def foreground(self) -> int: ...
    def log(self) -> list:
        return []


class FakeInput(InputBackend):
    def __init__(self) -> None:
        self.calls: list = []
        self._fg = 0
        self._lock = threading.Lock()

    def focus(self, hwnd: int) -> bool:
        with self._lock:
            self.calls.append(["focus", hwnd])
            self._fg = hwnd
        return True

    def keys(self, chords):
        with self._lock:
            self.calls.append(["keys", chords])

    def text(self, text):
        with self._lock:
            self.calls.append(["text", text])

    def click(self, x, y, button="left", count=1):
        with self._lock:
            self.calls.append(["click", x, y, button, count])

    def foreground(self) -> int:
        return self._fg

    def log(self) -> list:
        with self._lock:
            return list(self.calls)


# --------------------------------------------------------------------------------------------- real input

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class RealInput(InputBackend):
    KEYUP, UNICODE, EXTENDEDKEY = 0x2, 0x4, 0x1

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

    def _send(self, items: list[_INPUT]) -> None:
        arr = (_INPUT * len(items))(*items)
        sent = self.user32.SendInput(len(items), arr, ctypes.sizeof(_INPUT))
        if sent != len(items):
            raise OSError("Windows blocked the synthetic input (the target may be elevated, or the "
                          "desktop is locked).")

    def _key(self, vk: int, up: bool) -> _INPUT:
        flags = (self.KEYUP if up else 0) | (self.EXTENDEDKEY if vk in EXTENDED else 0)
        return _INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, 0)))

    def foreground(self) -> int:
        return self.user32.GetForegroundWindow() or 0

    def focus(self, hwnd: int) -> bool:
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        self.user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return self.foreground() == hwnd

    def keys(self, chords):
        for chord in chords:
            items = [self._key(vk, False) for vk in chord] + [self._key(vk, True) for vk in reversed(chord)]
            self._send(items)
            time.sleep(0.02)

    def text(self, text):
        for i in range(0, len(text), 200):
            items = []
            for ch in text[i:i + 200]:
                for code in (ord(c) for c in _utf16(ch)):
                    items.append(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(0, code, self.UNICODE, 0, 0))))
                    items.append(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(0, code, self.UNICODE | self.KEYUP, 0, 0))))
            self._send(items)

    def click(self, x, y, button="left", count=1):
        down, up = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}[button]
        self.user32.SetCursorPos(int(x), int(y))
        for _ in range(count):
            self._send([_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, down, 0, 0))),
                        _INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, up, 0, 0)))])


def _utf16(ch: str) -> str:
    """Split astral characters into surrogate pairs for KEYEVENTF_UNICODE."""
    code = ord(ch)
    if code < 0x10000:
        return ch
    code -= 0x10000
    return chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF))
