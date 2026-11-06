"""Which top-level windows are 'applications', and which application each belongs to.

Eligibility follows the taskbar/Alt+Tab rules: visible, not a tool window (unless WS_EX_APPWINDOW), unowned
(unless WS_EX_APPWINDOW), not cloaked by the shell, not a child window. Identity is the AppUserModelID
(explicit window property or packaged process) and otherwise the executable. Generic hosts (python.exe,
javaw.exe, ...) without an AUMID are split by window class so unrelated scripts don't merge into one icon.
"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from glass.core.apps import AppRecord, aumid_key, exe_key
from glass.win import shellcom
from glass.win.winapi import (GW_OWNER, GWL_EXSTYLE, GWL_STYLE, WNDENUMPROC, WS_CHILD, WS_EX_APPWINDOW,
                              WS_EX_TOOLWINDOW, class_name, cloaked, process_aumid, process_image, user32,
                              window_pid, window_rect, window_text)

GENERIC_HOSTS = {"python.exe", "pythonw.exe", "java.exe", "javaw.exe", "dotnet.exe", "wscript.exe", "cscript.exe",
                 "mshta.exe", "rundll32.exe", "dllhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe"}
NEVER_APPS = {"shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchhost.exe", "textinputhost.exe",
              "lockapp.exe", "systemsettingsbroker.exe", "widgets.exe", "widgetboard.exe"}
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
                 "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland"}


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    cls: str
    pid: int
    exe: str
    aumid: str
    rect: tuple[int, int, int, int]
    minimized: bool
    cloak: int

    @property
    def exe_name(self) -> str:
        return os.path.basename(self.exe).lower()

    def keys(self) -> list[str]:
        out = []
        if self.aumid:
            out.append(aumid_key(self.aumid))
        if self.exe and self.exe_name not in GENERIC_HOSTS and self.exe_name != "applicationframehost.exe":
            out.append(exe_key(self.exe))
        if not out:
            out.append(f"host:{self.exe_name}|{self.cls}")
        return out


def top_level_windows() -> list[int]:
    found: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _):
        found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def is_app_window(hwnd: int) -> bool:
    if not user32.IsWindowVisible(hwnd):
        return False
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if style & WS_CHILD:
        return False
    if ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW:
        return False
    if user32.GetWindow(hwnd, GW_OWNER) and not ex & WS_EX_APPWINDOW:
        return False
    if class_name(hwnd) in SHELL_CLASSES:
        return False
    # 1 = cloaked by the app, 2 = by the shell (other virtual desktop -- still an app window), 4 = inherited
    c = cloaked(hwnd)
    if c & 1 or c & 4:
        return False
    return True


_pid_cache: dict[int, tuple[str, str]] = {}
_pid_lock = threading.Lock()


def _process(pid: int) -> tuple[str, str]:
    with _pid_lock:
        hit = _pid_cache.get(pid)
    if hit is None:
        hit = (process_image(pid), process_aumid(pid))
        with _pid_lock:
            if len(_pid_cache) > 2000:
                _pid_cache.clear()
            _pid_cache[pid] = hit
    return hit


def window_info(hwnd: int) -> WindowInfo:
    pid = window_pid(hwnd)
    exe, proc_aumid = _process(pid)
    aumid = shellcom.window_aumid(hwnd) or proc_aumid
    return WindowInfo(hwnd=hwnd, title=window_text(hwnd), cls=class_name(hwnd), pid=pid, exe=exe, aumid=aumid,
                      rect=window_rect(hwnd), minimized=bool(user32.IsIconic(hwnd)), cloak=cloaked(hwnd))


# ------------------------------------------------------------------------------------------------ names

class _VSFixed(ctypes.Structure):
    _fields_ = [("sig", wintypes.DWORD), ("ver", wintypes.DWORD)] + [(f"f{i}", wintypes.DWORD) for i in range(11)]


_version = ctypes.WinDLL("version")
_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(wintypes.UINT)]
_desc_cache: dict[str, str] = {}


def file_description(exe: str) -> str:
    """The FileDescription from the exe's version resource ('Google Chrome'), else the file stem."""
    if not exe:
        return ""
    if exe in _desc_cache:
        return _desc_cache[exe]
    name = Path(exe).stem
    try:
        size = _version.GetFileVersionInfoSizeW(exe, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if _version.GetFileVersionInfoW(exe, 0, size, buf):
                ptr, n = ctypes.c_void_p(), wintypes.UINT()
                if _version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) and n.value >= 4:
                    lang, cp = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
                    sub = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                    if _version.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(n)) and n.value > 1:
                        desc = ctypes.wstring_at(ptr.value).strip()
                        if desc:
                            name = desc
    except OSError:
        pass
    _desc_cache[exe] = name
    return name


# ------------------------------------------------------------------------------------------------ catalog

@dataclass(frozen=True)
class CatalogEntry:
    name: str
    parsing: str          # AUMID, app id or path inside shell:AppsFolder
    target: str           # link target path ('' for Store apps)

    @property
    def launch(self) -> str:
        return "shell:AppsFolder\\" + self.parsing

    def record(self) -> AppRecord:
        is_path = os.path.isabs(self.parsing) or self.parsing[:1] == "{"
        exe = self.target if self.target.lower().endswith(".exe") else ""
        if not is_path:
            app_id = aumid_key(self.parsing)
            aumid = self.parsing
        else:
            app_id = exe_key(exe) if exe else exe_key(self.parsing)
            aumid = ""
        return AppRecord(app_id=app_id, name=self.name, exe=exe, aumid=aumid, launch=self.launch, icon=self.launch)

    def keys(self) -> list[str]:
        rec = self.record()
        keys = [rec.app_id]
        if rec.exe and exe_key(rec.exe) not in keys and os.path.basename(rec.exe).lower() not in GENERIC_HOSTS:
            keys.append(exe_key(rec.exe))
        return keys


class AppCatalog:
    """Installed applications as Windows lists them (Start menu + Store apps), indexed by identity key."""

    def __init__(self):
        self.entries: list[CatalogEntry] = []
        self._by_key: dict[str, CatalogEntry] = {}
        self._lock = threading.Lock()
        self.loaded = False

    def load(self) -> "AppCatalog":
        entries = []
        try:
            for name, parsing, target in shellcom.iter_apps_folder():
                if not name or not parsing:
                    continue
                low = (target or parsing).lower()
                if low.endswith((".txt", ".url", ".html", ".htm", ".pdf", ".chm", ".ini", ".md")):
                    continue  # documents and web links listed in the Start menu are not applications
                entries.append(CatalogEntry(name, parsing, target))
        except Exception:
            pass
        by_key: dict[str, CatalogEntry] = {}
        for e in entries:
            for k in e.keys():
                by_key.setdefault(k, e)
        with self._lock:
            self.entries = sorted(entries, key=lambda e: e.name.lower())
            self._by_key = by_key
            self.loaded = True
        return self

    def lookup(self, keys: list[str]) -> CatalogEntry | None:
        with self._lock:
            for k in keys:
                e = self._by_key.get(k)
                if e:
                    return e
        return None

    def search(self, text: str, limit: int = 50) -> list[CatalogEntry]:
        t = text.strip().lower()
        with self._lock:
            items = self.entries
        if not t:
            return items[:limit]
        starts = [e for e in items if e.name.lower().startswith(t)]
        contains = [e for e in items if t in e.name.lower() and e not in starts]
        return (starts + contains)[:limit]
