"""ctypes declarations shared by the Windows integration modules."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")

HWND = wintypes.HWND
LONG_PTR = ctypes.c_ssize_t

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, HWND, wintypes.LONG, wintypes.LONG,
                                  wintypes.DWORD, wintypes.DWORD)

# window styles / constants
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_MINIMIZE = 0x20000000
WS_MAXIMIZE = 0x01000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
GW_OWNER = 4
SW_HIDE, SW_SHOWNORMAL, SW_SHOWMINIMIZED, SW_MAXIMIZE, SW_SHOWNOACTIVATE, SW_SHOW = 0, 1, 2, 3, 4, 5
SW_MINIMIZE, SW_SHOWNA, SW_RESTORE = 6, 8, 9
WM_CLOSE = 0x0010
WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_NCRENDERING_POLICY = 2
DWMWA_EXCLUDED_FROM_PEEK = 12
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
WDA_EXCLUDEFROMCAPTURE = 0x11

# WinEvents
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_CLOAKED = 0x8017
EVENT_OBJECT_UNCLOAKED = 0x8018
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
CHILDID_SELF = 0


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    def tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right - self.left, self.bottom - self.top


def _proto(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


_proto(user32.EnumWindows, wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_proto(user32.IsWindow, wintypes.BOOL, HWND)
_proto(user32.IsWindowVisible, wintypes.BOOL, HWND)
_proto(user32.IsIconic, wintypes.BOOL, HWND)
_proto(user32.IsZoomed, wintypes.BOOL, HWND)
_proto(user32.GetWindowTextLengthW, ctypes.c_int, HWND)
_proto(user32.GetWindowTextW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
_proto(user32.GetClassNameW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
_proto(user32.GetWindowThreadProcessId, wintypes.DWORD, HWND, ctypes.POINTER(wintypes.DWORD))
_proto(user32.GetWindowLongPtrW, LONG_PTR, HWND, ctypes.c_int)
_proto(user32.GetWindow, HWND, HWND, wintypes.UINT)
_proto(user32.GetForegroundWindow, HWND)
_proto(user32.SetForegroundWindow, wintypes.BOOL, HWND)
_proto(user32.ShowWindow, wintypes.BOOL, HWND, ctypes.c_int)
_proto(user32.ShowWindowAsync, wintypes.BOOL, HWND, ctypes.c_int)
_proto(user32.PostMessageW, wintypes.BOOL, HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_proto(user32.GetWindowRect, wintypes.BOOL, HWND, ctypes.POINTER(RECT))
_proto(user32.FindWindowW, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_proto(user32.FindWindowExW, HWND, HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_proto(user32.SetWinEventHook, wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
       wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
_proto(user32.UnhookWinEvent, wintypes.BOOL, wintypes.HANDLE)
_proto(user32.RegisterWindowMessageW, wintypes.UINT, wintypes.LPCWSTR)
_proto(user32.SetWindowDisplayAffinity, wintypes.BOOL, HWND, wintypes.DWORD)
_proto(user32.GetAncestor, HWND, HWND, wintypes.UINT)
_proto(user32.AllowSetForegroundWindow, wintypes.BOOL, wintypes.DWORD)
_proto(user32.RegisterHotKey, wintypes.BOOL, HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_proto(user32.UnregisterHotKey, wintypes.BOOL, HWND, ctypes.c_int)
_proto(user32.SetWindowPos, wintypes.BOOL, HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
_proto(user32.SystemParametersInfoW, wintypes.BOOL, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
_proto(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_proto(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_proto(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_proto(kernel32.QueryFullProcessImageNameW, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
       ctypes.POINTER(wintypes.DWORD))
_proto(kernel32.GetApplicationUserModelId, ctypes.c_long, wintypes.HANDLE, ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR)
_proto(kernel32.GetCurrentProcessId, wintypes.DWORD)
_proto(dwmapi.DwmGetWindowAttribute, ctypes.c_long, HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
_proto(dwmapi.DwmSetWindowAttribute, ctypes.c_long, HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def window_text(hwnd: int) -> str:
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


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_image(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(h)


def process_aumid(pid: int) -> str:
    """AppUserModelID of a packaged (MSIX/UWP) process, '' for classic desktop processes."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        length = wintypes.UINT(512)
        buf = ctypes.create_unicode_buffer(512)
        return buf.value if kernel32.GetApplicationUserModelId(h, ctypes.byref(length), buf) == 0 else ""
    finally:
        kernel32.CloseHandle(h)


def cloaked(hwnd: int) -> int:
    val = wintypes.DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val)) != 0:
        return 0
    return val.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.tuple()


def set_dwm_int(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
