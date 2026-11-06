"""Output volume and mute via the documented Core Audio API (IAudioEndpointVolume), event-driven.

Switching the default output device has no documented API, so the UI opens Sound settings for that.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import POINTER, c_float, c_uint, c_void_p, wintypes

import comtypes
from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown
from PySide6.QtCore import QObject, Signal, Slot

from glass.win.shellcom import PROPERTYKEY, PROPVARIANT, IPropertyStore, ole32

log = logging.getLogger(__name__)

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
PKEY_Device_FriendlyName = PROPERTYKEY(GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}"), 14)
eRender, eConsole = 0, 0


class AUDIO_VOLUME_NOTIFICATION_DATA(ctypes.Structure):
    _fields_ = [("guidEventContext", GUID), ("bMuted", wintypes.BOOL), ("fMasterVolume", c_float),
                ("nChannels", c_uint), ("afChannelVolumes", c_float * 1)]


class IAudioEndpointVolumeCallback(IUnknown):
    _iid_ = GUID("{657804FA-D6AD-4496-8A60-352752AF4F89}")
    _methods_ = [COMMETHOD([], HRESULT, "OnNotify", (["in"], POINTER(AUDIO_VOLUME_NOTIFICATION_DATA), "pNotify"))]


class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], POINTER(IAudioEndpointVolumeCallback), "p")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], POINTER(IAudioEndpointVolumeCallback), "p")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "n")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "db"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "level"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "db")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "level")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "ch"), (["in"], c_float, "db"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "ch"), (["in"], c_float, "lvl"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "ch"), (["out"], POINTER(c_float), "db")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "ch"), (["out"], POINTER(c_float), "lvl")),
        COMMETHOD([], HRESULT, "SetMute", (["in"], wintypes.BOOL, "mute"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(wintypes.BOOL), "mute")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], wintypes.DWORD, "ctx"),
                  (["in"], c_void_p, "params"), (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], wintypes.DWORD, "access"), (["out"], POINTER(POINTER(IPropertyStore)), "pps")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "id")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(wintypes.DWORD), "state")),
    ]


class IMMNotificationClient(IUnknown):
    _iid_ = GUID("{7991EEC9-7E89-4D85-8390-6C703CEC60C0}")
    _methods_ = [
        COMMETHOD([], HRESULT, "OnDeviceStateChanged", (["in"], wintypes.LPCWSTR, "id"), (["in"], wintypes.DWORD, "state")),
        COMMETHOD([], HRESULT, "OnDeviceAdded", (["in"], wintypes.LPCWSTR, "id")),
        COMMETHOD([], HRESULT, "OnDeviceRemoved", (["in"], wintypes.LPCWSTR, "id")),
        COMMETHOD([], HRESULT, "OnDefaultDeviceChanged", (["in"], ctypes.c_int, "flow"), (["in"], ctypes.c_int, "role"),
                  (["in"], wintypes.LPCWSTR, "id")),
        COMMETHOD([], HRESULT, "OnPropertyValueChanged", (["in"], wintypes.LPCWSTR, "id"), (["in"], PROPERTYKEY, "key")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], ctypes.c_int, "flow"), (["in"], wintypes.DWORD, "mask"),
                  (["out"], POINTER(c_void_p), "devices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], ctypes.c_int, "flow"), (["in"], ctypes.c_int, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "endpoint")),
        COMMETHOD([], HRESULT, "GetDevice", (["in"], wintypes.LPCWSTR, "id"), (["out"], POINTER(POINTER(IMMDevice)), "dev")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], POINTER(IMMNotificationClient), "client")),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], POINTER(IMMNotificationClient), "client")),
    ]


class _VolumeCallback(COMObject):
    _com_interfaces_ = [IAudioEndpointVolumeCallback]

    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def OnNotify(self, pNotify):
        try:
            d = pNotify.contents
            self._sink(float(d.fMasterVolume), bool(d.bMuted))
        except Exception:
            pass
        return 0


class _DeviceCallback(COMObject):
    _com_interfaces_ = [IMMNotificationClient]

    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def OnDefaultDeviceChanged(self, flow, role, device_id):
        if flow == eRender and role == eConsole:
            self._sink()
        return 0

    def OnDeviceStateChanged(self, device_id, state):
        return 0

    def OnDeviceAdded(self, device_id):
        return 0

    def OnDeviceRemoved(self, device_id):
        return 0

    def OnPropertyValueChanged(self, device_id, key):
        return 0


class AudioService(QObject):
    changed = Signal(dict)
    _volumeEvent = Signal(float, bool)
    _deviceEvent = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enum = None
        self._vol = None
        self._vol_cb = None
        self._dev_cb = None
        self.state = {"available": False, "volume": 0.0, "muted": False, "device": ""}
        # COM callbacks arrive on audio threads; re-emit through queued signals onto the GUI thread.
        self._volumeEvent.connect(self._on_volume)
        self._deviceEvent.connect(self._attach)

    def start(self) -> None:
        try:
            self._enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_ALL)
            self._dev_cb = _DeviceCallback(lambda: self._deviceEvent.emit())
            self._enum.RegisterEndpointNotificationCallback(self._dev_cb)
        except (OSError, comtypes.COMError) as exc:
            log.warning("Core Audio unavailable: %s", exc)
            return
        self._attach()

    @Slot()
    def _attach(self) -> None:
        if self._vol is not None and self._vol_cb is not None:
            try:
                self._vol.UnregisterControlChangeNotify(self._vol_cb)
            except comtypes.COMError:
                pass
        self._vol = None
        try:
            dev = self._enum.GetDefaultAudioEndpoint(eRender, eConsole)
            ptr = dev.Activate(ctypes.byref(IAudioEndpointVolume._iid_), comtypes.CLSCTX_ALL, None)
            self._vol = ctypes.cast(c_void_p(ptr), POINTER(IAudioEndpointVolume))
            self._vol_cb = _VolumeCallback(lambda v, m: self._volumeEvent.emit(v, m))
            self._vol.RegisterControlChangeNotify(self._vol_cb)
            name = ""
            store = dev.OpenPropertyStore(0)
            pv = PROPVARIANT()
            try:
                store.GetValue(ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(pv))
                if pv.vt == 31 and pv.p:
                    name = ctypes.wstring_at(pv.p)
            finally:
                ole32.PropVariantClear(ctypes.byref(pv))
            self.state = {"available": True, "volume": float(self._vol.GetMasterVolumeLevelScalar()),
                          "muted": bool(self._vol.GetMute()), "device": name}
        except (OSError, comtypes.COMError) as exc:
            log.info("no default output device: %s", exc)
            self.state = {"available": False, "volume": 0.0, "muted": False, "device": ""}
        self.changed.emit(dict(self.state))

    @Slot(float, bool)
    def _on_volume(self, volume: float, muted: bool) -> None:
        changed = abs(volume - self.state.get("volume", 0)) > 1e-4 or muted != self.state.get("muted")
        self.state = {**self.state, "volume": volume, "muted": muted}
        if changed:
            self.changed.emit(dict(self.state))

    @Slot(float)
    def set_volume(self, level: float) -> None:
        if self._vol is not None:
            try:
                self._vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(level))), None)
            except comtypes.COMError as exc:
                log.debug("set volume failed: %s", exc)

    @Slot(bool)
    def set_muted(self, muted: bool) -> None:
        if self._vol is not None:
            try:
                self._vol.SetMute(bool(muted), None)
            except comtypes.COMError as exc:
                log.debug("set mute failed: %s", exc)
