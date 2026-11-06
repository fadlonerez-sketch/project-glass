"""Documented Shell COM interfaces (comtypes definitions) and helpers built on them.

* IShellItem / IShellItem2 / IEnumShellItems -- enumerate the Applications folder (shell:AppsFolder),
  read display names, parsing names (AUMIDs) and link targets.
* IShellItemImageFactory -- high-resolution application icons (Store logos included).
* IPropertyStore via SHGetPropertyStoreForWindow -- a window's AppUserModelID.
* IVirtualDesktopManager -- the documented virtual-desktop API (current-desktop test, desktop id).
* IDesktopWallpaper -- per-monitor wallpaper path, fit mode and background colour.
"""
from __future__ import annotations

import ctypes
import threading
import winreg
from ctypes import POINTER, byref, c_int, c_uint, c_void_p, wintypes

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

ole32 = ctypes.OleDLL("ole32")
shell32 = ctypes.OleDLL("shell32")
ole32.CoTaskMemFree.argtypes = [c_void_p]
ole32.CoTaskMemFree.restype = None


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("p", c_void_p), ("p2", c_void_p)]


ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]

PKEY_AppUserModel_ID = PROPERTYKEY(GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)
PKEY_Link_TargetParsingPath = PROPERTYKEY(GUID("{B9B4B3FC-2B51-4A42-B5D8-324146AFCF25}"), 2)
PKEY_AppUserModel_RelaunchCommand = PROPERTYKEY(GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 2)

BHID_EnumItems = GUID("{94f60519-2850-4924-aa5a-d15e84868039}")
FOLDERID_AppsFolder = GUID("{1e87508d-89c2-42f0-8a7e-645a0f50ca58}")
SIGDN_NORMALDISPLAY = 0
SIGDN_PARSING = 0x80018001  # SIGDN_PARENTRELATIVEPARSING: the AUMID or app id inside AppsFolder
SIGDN_DESKTOPABSOLUTEPARSING = 0x80028000


class SIZE(ctypes.Structure):
    _fields_ = [("cx", c_int), ("cy", c_int)]


class IShellItem(IUnknown):
    _iid_ = GUID("{43826d1e-e718-42ee-bc55-a1e261c37bfe}")


IShellItem._methods_ = [
    COMMETHOD([], HRESULT, "BindToHandler", (["in"], c_void_p, "pbc"), (["in"], POINTER(GUID), "bhid"),
              (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
    COMMETHOD([], HRESULT, "GetParent", (["out"], POINTER(POINTER(IShellItem)), "ppsi")),
    COMMETHOD([], HRESULT, "GetDisplayName", (["in"], c_uint, "sigdnName"), (["out"], POINTER(c_void_p), "ppszName")),
    COMMETHOD([], HRESULT, "GetAttributes", (["in"], wintypes.ULONG, "sfgaoMask"), (["out"], POINTER(wintypes.ULONG), "psfgaoAttribs")),
    COMMETHOD([], HRESULT, "Compare", (["in"], POINTER(IShellItem), "psi"), (["in"], wintypes.DWORD, "hint"),
              (["out"], POINTER(c_int), "piOrder")),
]


class IShellItem2(IShellItem):
    _iid_ = GUID("{7e9fb0d3-919f-4307-ab2e-9b1860310c93}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetPropertyStore", (["in"], c_int, "flags"), (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "GetPropertyStoreWithCreateObject", (["in"], c_int, "flags"), (["in"], c_void_p, "punk"),
                  (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "GetPropertyStoreForKeys", (["in"], c_void_p, "keys"), (["in"], c_uint, "n"), (["in"], c_int, "flags"),
                  (["in"], POINTER(GUID), "riid"), (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "GetPropertyDescriptionList", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(GUID), "riid"),
                  (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "Update", (["in"], c_void_p, "pbc")),
        COMMETHOD([], HRESULT, "GetProperty", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "ppropvar")),
        COMMETHOD([], HRESULT, "GetCLSID", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(GUID), "pclsid")),
        COMMETHOD([], HRESULT, "GetFileTime", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(wintypes.FILETIME), "pft")),
        COMMETHOD([], HRESULT, "GetInt32", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_int), "pi")),
        COMMETHOD([], HRESULT, "GetString", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_void_p), "ppsz")),
    ]


class IEnumShellItems(IUnknown):
    _iid_ = GUID("{70629033-e363-4a28-a567-0db78006e6d7}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Next", (["in"], wintypes.ULONG, "celt"), (["out"], POINTER(POINTER(IShellItem)), "rgelt"),
                  (["out"], POINTER(wintypes.ULONG), "pceltFetched")),
        COMMETHOD([], HRESULT, "Skip", (["in"], wintypes.ULONG, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(c_void_p), "ppenum")),
    ]


class IShellItemImageFactory(IUnknown):
    _iid_ = GUID("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetImage", (["in"], SIZE, "size"), (["in"], c_int, "flags"), (["out"], POINTER(wintypes.HBITMAP), "phbm")),
    ]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD), "cProps")),
        COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD, "iProp"), (["out"], POINTER(PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "Commit"),
    ]


class IVirtualDesktopManager(IUnknown):
    _iid_ = GUID("{a5cd92ff-29be-454c-8d04-d82879fb3f1b}")
    _methods_ = [
        COMMETHOD([], HRESULT, "IsWindowOnCurrentVirtualDesktop", (["in"], wintypes.HWND, "hwnd"),
                  (["out"], POINTER(wintypes.BOOL), "onCurrent")),
        COMMETHOD([], HRESULT, "GetWindowDesktopId", (["in"], wintypes.HWND, "hwnd"), (["out"], POINTER(GUID), "desktopId")),
        COMMETHOD([], HRESULT, "MoveWindowToDesktop", (["in"], wintypes.HWND, "hwnd"), (["in"], POINTER(GUID), "desktopId")),
    ]


CLSID_VirtualDesktopManager = GUID("{aa509086-5ca9-4c25-8f95-589d3c07b48a}")


class IDesktopWallpaper(IUnknown):
    _iid_ = GUID("{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}")
    _methods_ = [
        COMMETHOD([], HRESULT, "SetWallpaper", (["in"], wintypes.LPCWSTR, "monitorID"), (["in"], wintypes.LPCWSTR, "wallpaper")),
        COMMETHOD([], HRESULT, "GetWallpaper", (["in"], wintypes.LPCWSTR, "monitorID"), (["out"], POINTER(c_void_p), "wallpaper")),
        COMMETHOD([], HRESULT, "GetMonitorDevicePathAt", (["in"], c_uint, "index"), (["out"], POINTER(c_void_p), "monitorID")),
        COMMETHOD([], HRESULT, "GetMonitorDevicePathCount", (["out"], POINTER(c_uint), "count")),
        COMMETHOD([], HRESULT, "GetMonitorRECT", (["in"], wintypes.LPCWSTR, "monitorID"), (["out"], POINTER(wintypes.RECT), "displayRect")),
        COMMETHOD([], HRESULT, "SetBackgroundColor", (["in"], wintypes.DWORD, "color")),
        COMMETHOD([], HRESULT, "GetBackgroundColor", (["out"], POINTER(wintypes.DWORD), "color")),
        COMMETHOD([], HRESULT, "SetPosition", (["in"], c_int, "position")),
        COMMETHOD([], HRESULT, "GetPosition", (["out"], POINTER(c_int), "position")),
    ]


CLSID_DesktopWallpaper = GUID("{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}")

shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetKnownFolderItem.argtypes = [POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, POINTER(GUID), POINTER(c_void_p)]
shell32.SHGetKnownFolderPath.argtypes = [POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, POINTER(c_void_p)]

_local = threading.local()


def ensure_com() -> None:
    """Initialise COM on the calling thread once (STA on the GUI thread, which comtypes already did)."""
    if not getattr(_local, "com", False):
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except OSError:
            pass  # already initialised in another mode on this thread; that is fine for these APIs
        _local.com = True


def _take_string(ptr) -> str:
    value = ptr.value if hasattr(ptr, "value") else ptr
    if not value:
        return ""
    try:
        return ctypes.wstring_at(value)
    finally:
        ole32.CoTaskMemFree(value)


def _query(punk_ptr: int, iface):
    unk = ctypes.cast(c_void_p(punk_ptr), POINTER(iface))
    return unk


def item_from_parsing_name(name: str, iface=IShellItem2):
    ensure_com()
    out = c_void_p()
    shell32.SHCreateItemFromParsingName(name, None, byref(iface._iid_), byref(out))
    return _query(out.value, iface)


def display_name(item, sigdn: int = SIGDN_NORMALDISPLAY) -> str:
    try:
        return _take_string(item.GetDisplayName(sigdn))
    except comtypes.COMError:
        return ""


def item_string(item, key: PROPERTYKEY) -> str:
    try:
        return _take_string(item.GetString(byref(key)))
    except (comtypes.COMError, OSError):
        return ""


def iter_apps_folder():
    """Yield (display name, parsing name, link target) for each entry of shell:AppsFolder."""
    ensure_com()
    folder_ptr = c_void_p()
    shell32.SHGetKnownFolderItem(byref(FOLDERID_AppsFolder), 0, None, byref(IShellItem._iid_), byref(folder_ptr))
    folder = _query(folder_ptr.value, IShellItem)
    enum_ptr = folder.BindToHandler(None, byref(BHID_EnumItems), byref(IEnumShellItems._iid_))
    enum = _query(enum_ptr, IEnumShellItems)
    while True:
        try:
            item, fetched = enum.Next(1)
        except comtypes.COMError:
            break
        if not fetched or not item:
            break
        item2 = item.QueryInterface(IShellItem2)
        yield (display_name(item2), display_name(item2, SIGDN_PARSING), item_string(item2, PKEY_Link_TargetParsingPath))


def window_aumid(hwnd: int) -> str:
    """Explicit AppUserModelID set on a window (Chrome profiles, Store apps' frame windows, ...)."""
    ensure_com()
    out = c_void_p()
    try:
        shell32.SHGetPropertyStoreForWindow(hwnd, byref(IPropertyStore._iid_), byref(out))
    except OSError:
        return ""
    store = _query(out.value, IPropertyStore)
    pv = PROPVARIANT()
    try:
        store.GetValue(byref(PKEY_AppUserModel_ID), byref(pv))
        if pv.vt == 31 and pv.p:  # VT_LPWSTR
            return ctypes.wstring_at(pv.p)
        return ""
    except comtypes.COMError:
        return ""
    finally:
        ole32.PropVariantClear(byref(pv))


def known_folder_path(guid: str) -> str:
    out = c_void_p()
    try:
        shell32.SHGetKnownFolderPath(byref(GUID(guid)), 0, None, byref(out))
    except OSError:
        return ""
    return _take_string(out)


# ------------------------------------------------------------------------------------------- virtual desktops

class VirtualDesktops:
    """The documented IVirtualDesktopManager plus the desktop names Explorer stores in the registry."""

    _KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops\Desktops"

    def __init__(self):
        ensure_com()
        try:
            self._mgr = comtypes.CoCreateInstance(CLSID_VirtualDesktopManager, IVirtualDesktopManager)
        except (OSError, comtypes.COMError):
            self._mgr = None

    @property
    def available(self) -> bool:
        return self._mgr is not None

    def on_current(self, hwnd: int) -> bool:
        if self._mgr is None:
            return True
        try:
            return bool(self._mgr.IsWindowOnCurrentVirtualDesktop(hwnd))
        except comtypes.COMError:
            return True  # windows Windows can't place (e.g. tool windows) count as visible everywhere

    def desktop_id(self, hwnd: int) -> str:
        if self._mgr is None:
            return ""
        try:
            return str(self._mgr.GetWindowDesktopId(hwnd)).upper()
        except comtypes.COMError:
            return ""

    def names(self) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._KEY) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, sub) as dk:
                            out[sub.upper()] = str(winreg.QueryValueEx(dk, "Name")[0])
                    except OSError:
                        continue
        except OSError:
            pass
        return out


# ------------------------------------------------------------------------------------------- wallpaper

POSITIONS = {0: "center", 1: "tile", 2: "stretch", 3: "fit", 4: "fill", 5: "span"}


def wallpapers() -> list[dict]:
    """[{monitor, rect:(x,y,w,h), path, position, background:'#RRGGBB'}] for every monitor."""
    ensure_com()
    try:
        dw = comtypes.CoCreateInstance(CLSID_DesktopWallpaper, IDesktopWallpaper)
    except (OSError, comtypes.COMError):
        return []
    out = []
    try:
        count = dw.GetMonitorDevicePathCount()
        position = POSITIONS.get(dw.GetPosition(), "fill")
        bg = dw.GetBackgroundColor()
        bg_hex = "#{:02X}{:02X}{:02X}".format(bg & 0xFF, (bg >> 8) & 0xFF, (bg >> 16) & 0xFF)
        for i in range(count):
            mon = _take_string(dw.GetMonitorDevicePathAt(i))
            try:
                r = dw.GetMonitorRECT(mon)
            except comtypes.COMError:
                continue  # detached monitor
            try:
                path = _take_string(dw.GetWallpaper(mon))
            except comtypes.COMError:
                path = ""
            out.append({"monitor": mon, "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top),
                        "path": path, "position": position, "background": bg_hex})
    except comtypes.COMError:
        return out
    return out
