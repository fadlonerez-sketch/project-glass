"""A plain Win32 test target built with ctypes (standard USER32 controls, no toolkit).

Its standard controls get Windows' built-in UI Automation proxies -- ListBox (Scroll + Selection),
Edit (Value), Button/CheckBox (Invoke/Toggle) -- so it exercises the 'Win32' framework path, including
ScrollPattern, which Qt widgets don't implement. `--blank` makes a captionless window with no
children: the shape of a custom-drawn surface that exposes nothing (coverage 'none').

The window is created off-screen, shown with SW_SHOWNOACTIVATE and is a tool window: it never takes
focus and has no taskbar button.
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WS_OVERLAPPEDWINDOW, WS_POPUP, WS_CHILD, WS_VISIBLE, WS_VSCROLL, WS_BORDER, WS_TABSTOP = (
    0x00CF0000, 0x80000000, 0x40000000, 0x10000000, 0x00200000, 0x00800000, 0x00010000)
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
LBS_NOTIFY, BS_AUTOCHECKBOX, BS_PUSHBUTTON = 0x1, 0x3, 0x0
LB_ADDSTRING, WM_COMMAND, WM_DESTROY, WM_VSCROLL = 0x0180, 0x0111, 0x0002, 0x0115
LBN_SELCHANGE, BN_CLICKED, EN_CHANGE = 1, 0, 0x0300
ID_LIST, ID_EDIT, ID_CHECK, ID_BUTTON, ID_STATUS, ID_TREE = 101, 102, 103, 104, 105, 106
TVS_HASBUTTONS, TVS_HASLINES, TVS_LINESATROOT = 0x1, 0x2, 0x4
TVM_INSERTITEMW, TVIF_TEXT, TVI_LAST = 0x1132, 0x1, -0xFFFE


class TVITEMW(ctypes.Structure):
    _fields_ = [("mask", wintypes.UINT), ("hItem", ctypes.c_void_p), ("state", wintypes.UINT),
                ("stateMask", wintypes.UINT), ("pszText", wintypes.LPWSTR), ("cchTextMax", ctypes.c_int),
                ("iImage", ctypes.c_int), ("iSelectedImage", ctypes.c_int), ("cChildren", ctypes.c_int),
                ("lParam", ctypes.c_ssize_t)]


class TVINSERTSTRUCTW(ctypes.Structure):
    _fields_ = [("hParent", ctypes.c_void_p), ("hInsertAfter", ctypes.c_void_p), ("item", TVITEMW)]


def tree_insert(tree, parent, text):
    ins = TVINSERTSTRUCTW(parent, TVI_LAST, TVITEMW(TVIF_TEXT, None, 0, 0, text, len(text), 0, 0, 0, 0))
    return user32.SendMessageW(tree, TVM_INSERTITEMW, 0, ctypes.cast(ctypes.byref(ins), ctypes.c_void_p).value)

state = {}


def set_status(text: str) -> None:
    user32.SetWindowTextW(state["status"], text)


@WNDPROC
def wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_COMMAND:
        ident, code = wparam & 0xFFFF, (wparam >> 16) & 0xFFFF
        if ident == ID_BUTTON and code == BN_CLICKED:
            set_status("win32:clicked")
        elif ident == ID_CHECK and code == BN_CLICKED:
            checked = user32.SendMessageW(state["check"], 0x00F0, 0, 0)  # BM_GETCHECK
            set_status(f"win32:checked:{bool(checked)}")
        elif ident == ID_LIST and code == LBN_SELCHANGE:
            idx = user32.SendMessageW(state["list"], 0x0188, 0, 0)  # LB_GETCURSEL
            set_status(f"win32:selected:{idx}")
        elif ident == ID_EDIT and code == EN_CHANGE:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(state["edit"], buf, 256)
            set_status(f"win32:text:{buf.value}")
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Glass Win32 Target")
    ap.add_argument("--blank", action="store_true")
    args = ap.parse_args()
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinst
    wc.lpszClassName = "GlassWin32Target"
    wc.hbrBackground = 6  # COLOR_WINDOW + 1
    ctypes.WinDLL("comctl32").InitCommonControls()
    user32.RegisterClassW(ctypes.byref(wc))
    style = WS_POPUP if args.blank else WS_OVERLAPPEDWINDOW
    hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "GlassWin32Target", args.title, style,
                                  -32000, -32000, 420, 520, None, None, hinst, None)
    if not args.blank:
        mk = lambda cls, text, st, x, y, w, h, ident: user32.CreateWindowExW(  # noqa: E731
            0, cls, text, WS_CHILD | WS_VISIBLE | WS_TABSTOP | st, x, y, w, h, hwnd, ident, hinst, None)
        state["status"] = mk("STATIC", "win32:ready", 0, 10, 10, 380, 22, ID_STATUS)
        state["button"] = mk("BUTTON", "Press Me", BS_PUSHBUTTON, 10, 40, 120, 28, ID_BUTTON)
        state["check"] = mk("BUTTON", "Remember", BS_AUTOCHECKBOX, 140, 40, 150, 28, ID_CHECK)
        state["edit"] = mk("EDIT", "", WS_BORDER, 10, 76, 380, 24, ID_EDIT)
        state["list"] = mk("LISTBOX", "", WS_VSCROLL | WS_BORDER | LBS_NOTIFY, 10, 110, 380, 200, ID_LIST)
        state["tree"] = mk("SysTreeView32", "", WS_BORDER | TVS_HASBUTTONS | TVS_HASLINES | TVS_LINESATROOT,
                           10, 320, 380, 150, ID_TREE)
        root = tree_insert(state["tree"], None, "Projects")
        tree_insert(state["tree"], root, "Glass")
        tree_insert(state["tree"], root, "Garvis")
        for i in range(100):
            text = ctypes.create_unicode_buffer(f"Item {i}")  # kept alive for the synchronous call
            user32.SendMessageW(state["list"], LB_ADDSTRING, 0, ctypes.addressof(text))
    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    print("READY", int(hwnd), flush=True)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
