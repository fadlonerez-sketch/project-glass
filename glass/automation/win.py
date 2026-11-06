"""Win32 window facts and window operations for the engine (ctypes only, no screenshots).

Everything here is read-only except the explicit window operations (`set_state`, `move`), which use
asynchronous Win32 calls so a hung target cannot freeze the engine.
"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from functools import lru_cache

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
version = ctypes.WinDLL("version")

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetPropW.restype = wintypes.HANDLE
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GA_ROOTOWNER = 3
GA_ROOT = 2
GW_OWNER = 4
DWMWA_CLOAKED = 14
PROTECTED_PROP = "ProjectGlass.Protected"

# ShowWindow commands that never activate the target (the user's focus stays where it is).
SW_SHOWMINNOACTIVE = 7
SW_SHOWNOACTIVATE = 4
SW_SHOWMAXIMIZED = 3
WM_CLOSE = 0x0010
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_ASYNCWINDOWPOS = 0x4000


def enable_dpi_awareness() -> None:
    """Physical-pixel coordinates everywhere (UIA rects, window rects)."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        pass


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def rect_of(hwnd: int) -> list[int]:
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return [0, 0, 0, 0]
    return [r.left, r.top, r.right - r.left, r.bottom - r.top]


def state_of(hwnd: int) -> str:
    if user32.IsIconic(hwnd):
        return "minimized"
    if user32.IsZoomed(hwnd):
        return "maximized"
    return "normal"


def cloaked(hwnd: int) -> int:
    val = wintypes.DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val)) != 0:
        return 0
    return val.value


def root_window(hwnd: int) -> int:
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def is_protected(hwnd: int) -> bool:
    """Project Glass marks its own windows (Shell, Control Center) so clients can't drive them."""
    seen = set()
    h = hwnd
    while h and h not in seen:
        seen.add(h)
        if user32.GetPropW(h, PROTECTED_PROP):
            return True
        h = user32.GetWindow(h, GW_OWNER) or user32.GetAncestor(h, GA_ROOT)
        if h in seen:
            break
    return False


@lru_cache(maxsize=512)
def _image_for_pid(pid: int, _gen: int = 0) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def image_of(pid: int) -> str:
    return _image_for_pid(pid) if pid else ""


@lru_cache(maxsize=512)
def friendly_name(path: str) -> str:
    """FileDescription from the version resource, falling back to the exe stem."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if not path:
        return ""
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(path, 0, size, buf):
                ptr = ctypes.c_void_p()
                ln = wintypes.UINT()
                if version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value >= 4:
                    lang, cp = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
                    key = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                    sptr = ctypes.c_wchar_p()
                    if version.VerQueryValueW(buf, key, ctypes.byref(sptr), ctypes.byref(ln)) and sptr.value:
                        return sptr.value.strip()
    except Exception:
        pass
    return stem[:1].upper() + stem[1:]


_self_elevated: bool | None = None


def _token_elevated(process_handle) -> bool | None:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, 0x0008, ctypes.byref(token)):
        return None
    try:
        elevated = wintypes.DWORD()
        size = wintypes.DWORD()
        if not advapi32.GetTokenInformation(token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)):
            return None
        return bool(elevated.value)
    finally:
        kernel32.CloseHandle(token)


def self_elevated() -> bool:
    global _self_elevated
    if _self_elevated is None:
        _self_elevated = bool(_token_elevated(kernel32.GetCurrentProcess()))
    return _self_elevated


def is_elevated(pid: int) -> bool:
    """True when the process runs elevated and we don't (UIPI then blocks driving it)."""
    if self_elevated() or not pid:
        return False
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        res = _token_elevated(h)
        # Access to an elevated process's token is denied to a medium-integrity caller.
        return True if res is None else res
    finally:
        kernel32.CloseHandle(h)


# --------------------------------------------------------------------------------------------- virtual desktops

class _VDM:
    """IVirtualDesktopManager (documented shell API) -- is a window on the current virtual desktop?"""

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._mgr = None
        self._failed = False

    def _ensure(self):
        if self._mgr is not None or self._failed:
            return self._mgr
        try:
            import comtypes
            import comtypes.client
            from comtypes import GUID, COMMETHOD, HRESULT

            class IVirtualDesktopManager(comtypes.IUnknown):
                _iid_ = GUID("{a5cd92ff-29be-454c-8d04-d82879fb3f1b}")
                _methods_ = [
                    COMMETHOD([], HRESULT, "IsWindowOnCurrentVirtualDesktop",
                              (["in"], wintypes.HWND, "topLevelWindow"),
                              (["out", "retval"], ctypes.POINTER(wintypes.BOOL), "onCurrentDesktop")),
                    COMMETHOD([], HRESULT, "GetWindowDesktopId",
                              (["in"], wintypes.HWND, "topLevelWindow"),
                              (["out", "retval"], ctypes.POINTER(GUID), "desktopId")),
                ]

            self._mgr = comtypes.client.CreateObject(GUID("{aa509086-5ca9-4c25-8f95-589d3c07b48a}"),
                                                     interface=IVirtualDesktopManager)
        except Exception:
            self._failed = True
        return self._mgr

    def on_current(self, hwnd: int) -> bool | None:
        mgr = self._ensure()
        if mgr is None:
            return None
        try:
            return bool(mgr.IsWindowOnCurrentVirtualDesktop(hwnd))
        except Exception:
            return None


_vdm_local = threading.local()


def on_current_desktop(hwnd: int) -> bool:
    vdm = getattr(_vdm_local, "vdm", None)
    if vdm is None:
        vdm = _vdm_local.vdm = _VDM()
    res = vdm.on_current(hwnd)
    if res is None:
        return cloaked(hwnd) == 0
    return res


# --------------------------------------------------------------------------------------------- enumeration

def top_level_windows(include_hidden: bool = False) -> list[int]:
    out: list[int] = []

    def cb(hwnd, _lp):
        if include_hidden or user32.IsWindowVisible(hwnd):
            out.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def describe(hwnd: int) -> dict:
    pid = pid_of(hwnd)
    image = image_of(pid)
    fg = user32.GetForegroundWindow()
    return {
        "hwnd": hwnd,
        "title": title(hwnd),
        "app": friendly_name(image) if image else "",
        "exe": os.path.basename(image),
        "pid": pid,
        "rect": rect_of(hwnd),
        "state": state_of(hwnd),
        "foreground": bool(fg) and fg == hwnd,
        "on_current_desktop": on_current_desktop(hwnd),
        "elevated": is_elevated(pid),
    }


def list_windows(all_desktops: bool = False, include_hidden: bool = False) -> list[dict]:
    """User-meaningful top-level windows: titled, not cloaked (unless all desktops)."""
    result = []
    for hwnd in top_level_windows(include_hidden):
        t = title(hwnd)
        if not t and not include_hidden:
            continue
        c = cloaked(hwnd)
        if c and not all_desktops and not include_hidden:
            continue
        info = describe(hwnd)
        if not all_desktops and not info["on_current_desktop"] and not include_hidden:
            continue
        result.append(info)
    return result


def window_ids(include_hidden: bool = False) -> set[int]:
    return {h for h in top_level_windows(include_hidden) if title(h)}


# --------------------------------------------------------------------------------------------- operations

def set_state(hwnd: int, state: str) -> None:
    if state == "minimize":
        user32.ShowWindowAsync(hwnd, SW_SHOWMINNOACTIVE)
    elif state == "maximize":
        user32.ShowWindowAsync(hwnd, SW_SHOWMAXIMIZED)
    elif state == "restore":
        user32.ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE)
    elif state == "close":
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    else:
        raise ValueError(state)


def move(hwnd: int, x: int | None, y: int | None, width: int | None, height: int | None) -> None:
    cur = rect_of(hwnd)
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
    nx, ny = (cur[0] if x is None else x), (cur[1] if y is None else y)
    nw, nh = (cur[2] if width is None else width), (cur[3] if height is None else height)
    if x is None and y is None:
        flags |= SWP_NOMOVE
    if width is None and height is None:
        flags |= SWP_NOSIZE
    user32.SetWindowPos(hwnd, None, nx, ny, nw, nh, flags)


def foreground() -> int:
    return user32.GetForegroundWindow() or 0
