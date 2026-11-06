"""Launching applications and managing their windows (documented user32 / ShellExecute only)."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from ctypes import wintypes

from glass.win.winapi import (SW_MINIMIZE, SW_RESTORE, SW_SHOWNA, WM_CLOSE, user32)

log = logging.getLogger(__name__)

_shell32 = ctypes.WinDLL("shell32")
_shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, ctypes.c_int]
_shell32.ShellExecuteW.restype = ctypes.c_void_p


class LaunchError(Exception):
    pass


def launch(target: str) -> None:
    """Start an app from a shortcut, exe or shell:AppsFolder\\<id> (Store and desktop apps alike)."""
    if not target:
        raise LaunchError("This app has no launch target.")
    if target.lower().startswith("shell:appsfolder\\"):
        # Explorer resolves AppsFolder ids for both packaged and desktop apps (same as the Start menu).
        windir = os.environ.get("WINDIR", r"C:\Windows")
        subprocess.Popen([os.path.join(windir, "explorer.exe"), target], shell=False,
                         creationflags=subprocess.DETACHED_PROCESS)
        return
    rc = _shell32.ShellExecuteW(None, "open", target, None, os.path.dirname(target) or None, 1)
    if (rc or 0) <= 32:
        raise LaunchError(f"Windows could not start {os.path.basename(target)} (code {rc}).")


def activate(hwnd: int) -> bool:
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindowAsync(hwnd, SW_RESTORE)
    ok = bool(user32.SetForegroundWindow(hwnd))
    if not ok:
        log.info("SetForegroundWindow refused for %#x", hwnd)
    return ok


def minimize(hwnd: int) -> None:
    user32.ShowWindowAsync(hwnd, SW_MINIMIZE)


def close(hwnd: int) -> None:
    """Ask politely (WM_CLOSE): the app may prompt to save; nothing is killed."""
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def show_no_activate(hwnd: int) -> None:
    user32.ShowWindowAsync(hwnd, SW_SHOWNA)


def open_uri(uri: str) -> None:
    os.startfile(uri)
