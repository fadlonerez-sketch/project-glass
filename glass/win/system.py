"""Battery and network status (WinRT, event-driven) plus Wi-Fi control where Windows permits it.

Where Windows offers no supported API (power mode, Bluetooth pairing, new Wi-Fi networks that need more
than a password, ...), the UI opens the matching Settings page instead of pretending to act.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from glass.win.winrt_worker import WinRtWorker

log = logging.getLogger(__name__)

try:
    from winrt.windows.system.power import (BatteryStatus, EnergySaverStatus, PowerManager, PowerSupplyStatus)
    from winrt.windows.devices.power import Battery
    POWER = True
except Exception:  # pragma: no cover
    POWER = False

try:
    from winrt.windows.networking.connectivity import NetworkConnectivityLevel, NetworkInformation
    NETWORK = True
except Exception:  # pragma: no cover
    NETWORK = False

SETTINGS_PAGES = {
    "battery": "ms-settings:batterysaver",
    "power": "ms-settings:powersleep",
    "network": "ms-settings:network-status",
    "wifi": "ms-settings:network-wifi",
    "wifi_networks": "ms-settings:network-wifisettings",
    "ethernet": "ms-settings:network-ethernet",
    "vpn": "ms-settings:network-vpn",
    "airplane": "ms-settings:network-airplanemode",
    "bluetooth": "ms-settings:bluetooth",
    "sound": "ms-settings:sound",
    "sound_devices": "ms-settings:sound-devices",
    "volume_mixer": "ms-settings:apps-volume",
    "display": "ms-settings:display",
    "night_light": "ms-settings:nightlight",
    "notifications": "ms-settings:notifications",
    "focus": "ms-settings:quiethours",
    "taskbar": "ms-settings:taskbar",
    "personalization": "ms-settings:personalization-background",
    "startup": "ms-settings:startupapps",
    "location": "ms-settings:privacy-location",
}


def open_settings_page(name: str) -> bool:
    uri = SETTINGS_PAGES.get(name, name if name.startswith("ms-settings:") else "")
    if not uri:
        return False
    try:
        os.startfile(uri)  # documented ms-settings: URI scheme
        return True
    except OSError as exc:
        log.warning("could not open %s: %s", uri, exc)
        return False


class PowerService(QObject):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tokens = []
        self.state: dict[str, Any] = {"present": False}

    def start(self) -> None:
        if not POWER:
            return
        for name in ("remaining_charge_percent_changed", "battery_status_changed", "power_supply_status_changed",
                     "energy_saver_status_changed", "remaining_discharge_time_changed"):
            try:
                self._tokens.append((name, getattr(PowerManager, "add_" + name)(lambda *_: self.refresh())))
            except Exception as exc:
                log.debug("power event %s unavailable: %s", name, exc)
        self.refresh()

    def refresh(self) -> None:
        try:
            status = PowerManager.battery_status
            supply = PowerManager.power_supply_status
            present = status != BatteryStatus.NOT_PRESENT
            st = {
                "present": present,
                "percent": int(PowerManager.remaining_charge_percent),
                "charging": status == BatteryStatus.CHARGING,
                "plugged": supply != PowerSupplyStatus.NOT_PRESENT,
                "saver": PowerManager.energy_saver_status == EnergySaverStatus.ON,
            }
            try:
                secs = PowerManager.remaining_discharge_time.total_seconds()
                st["remaining_min"] = int(secs // 60) if 0 < secs < 7 * 24 * 3600 and not st["plugged"] else None
            except Exception:
                st["remaining_min"] = None
            try:
                rep = Battery.aggregate_battery.get_report()
                full = rep.full_charge_capacity_in_milliwatt_hours
                design = rep.design_capacity_in_milliwatt_hours
                rate = rep.charge_rate_in_milliwatts
                st["health"] = round(100 * full / design) if full and design else None
                st["rate_w"] = round(rate / 1000, 1) if rate is not None else None
            except Exception:
                st["health"] = st["rate_w"] = None
        except Exception as exc:
            log.debug("power refresh failed: %s", exc)
            return
        self.state = st
        self.changed.emit(dict(st))


class NetworkService(QObject):
    changed = Signal(dict)
    wifiNetworks = Signal(list)
    wifiResult = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = WinRtWorker.shared()
        self._token = None
        self.state: dict[str, Any] = {"kind": "none", "internet": False}
        self._adapter = None
        self._networks: dict[str, Any] = {}

    def start(self) -> None:
        if not NETWORK:
            return
        try:
            self._token = NetworkInformation.add_network_status_changed(lambda *_: self.refresh())
        except Exception as exc:
            log.debug("network events unavailable: %s", exc)
        self.refresh()

    def refresh(self) -> None:
        st: dict[str, Any] = {"kind": "none", "internet": False, "name": "", "ssid": "", "bars": 0, "level": "none"}
        try:
            prof = NetworkInformation.get_internet_connection_profile()
            if prof is not None:
                level = prof.get_network_connectivity_level()
                st["internet"] = level == NetworkConnectivityLevel.INTERNET_ACCESS
                st["level"] = {NetworkConnectivityLevel.NONE: "none", NetworkConnectivityLevel.LOCAL_ACCESS: "local",
                               NetworkConnectivityLevel.CONSTRAINED_INTERNET_ACCESS: "constrained",
                               NetworkConnectivityLevel.INTERNET_ACCESS: "internet"}.get(level, "none")
                st["name"] = prof.profile_name or ""
                if prof.is_wlan_connection_profile:
                    st["kind"] = "wifi"
                    try:
                        st["ssid"] = prof.wlan_connection_profile_details.get_connected_ssid() or st["name"]
                    except Exception:
                        st["ssid"] = st["name"]
                elif prof.is_wwan_connection_profile:
                    st["kind"] = "cellular"
                else:
                    st["kind"] = "ethernet"
                try:
                    bars = prof.get_signal_bars()
                    st["bars"] = int(bars) if bars is not None else (5 if st["kind"] != "wifi" else 0)
                except Exception:
                    st["bars"] = 0
        except Exception as exc:
            log.debug("network refresh failed: %s", exc)
        self.state = st
        self.changed.emit(dict(st))

    # ------------------------------------------------------------------ Wi-Fi (supported WinRT APIs only)
    @Slot()
    def scan_wifi(self) -> None:
        self._worker.submit(self._scan(), lambda r, e: self.wifiNetworks.emit(r if e is None else [{"error": str(e)}]))

    async def _scan(self) -> list[dict]:
        from winrt.windows.devices.wifi import WiFiAccessStatus, WiFiAdapter
        access = await WiFiAdapter.request_access_async()
        if access != WiFiAccessStatus.ALLOWED:
            return [{"error": "Windows did not allow Wi-Fi scanning (check Location privacy settings)."}]
        adapters = await WiFiAdapter.find_all_adapters_async()
        if not adapters or adapters.size == 0:
            return [{"error": "No Wi-Fi adapter found."}]
        self._adapter = adapters.get_at(0)
        await self._adapter.scan_async()
        current = self.state.get("ssid", "")
        best: dict[str, Any] = {}
        for n in self._adapter.network_report.available_networks:
            ssid = n.ssid or ""
            if not ssid:
                continue
            if ssid not in best or n.signal_bars > best[ssid].signal_bars:
                best[ssid] = n
        self._networks = best
        out = []
        for ssid, n in sorted(best.items(), key=lambda kv: (kv[0] != current, -kv[1].signal_bars, kv[0].lower())):
            secured = True
            try:
                from winrt.windows.networking.connectivity import NetworkAuthenticationType
                secured = n.security_settings.network_authentication_type not in (
                    NetworkAuthenticationType.OPEN80211, NetworkAuthenticationType.NONE)
            except Exception:
                pass
            out.append({"ssid": ssid, "bars": int(n.signal_bars), "secured": secured, "connected": ssid == current})
        return out

    @Slot(str, str)
    def connect_wifi(self, ssid: str, password: str = "") -> None:
        self._worker.submit(self._connect(ssid, password),
                            lambda r, e: self.wifiResult.emit(r if e is None else {"ok": False, "ssid": ssid, "error": str(e)}))

    async def _connect(self, ssid: str, password: str) -> dict:
        from winrt.windows.devices.wifi import WiFiConnectionStatus, WiFiReconnectionKind
        net = self._networks.get(ssid)
        if self._adapter is None or net is None:
            return {"ok": False, "ssid": ssid, "error": "Scan for networks first."}
        if password:
            from winrt.windows.security.credentials import PasswordCredential
            cred = PasswordCredential()
            cred.password = password
            res = await self._adapter.connect_with_password_credential_async(net, WiFiReconnectionKind.AUTOMATIC, cred)
        else:
            res = await self._adapter.connect_async(net, WiFiReconnectionKind.AUTOMATIC)
        ok = res.connection_status == WiFiConnectionStatus.SUCCESS
        reason = {WiFiConnectionStatus.INVALID_CREDENTIAL: "The password was not accepted.",
                  WiFiConnectionStatus.NETWORK_NOT_AVAILABLE: "The network is out of range.",
                  WiFiConnectionStatus.TIMEOUT: "The connection timed out.",
                  WiFiConnectionStatus.ACCESS_REVOKED: "Windows revoked Wi-Fi access.",
                  WiFiConnectionStatus.UNSUPPORTED_AUTHENTICATION_PROTOCOL: "This network needs Windows Settings to join."}
        return {"ok": ok, "ssid": ssid, "error": "" if ok else reason.get(res.connection_status, "Could not connect.")}

    @Slot(bool)
    def set_wifi_enabled(self, enabled: bool) -> None:
        self._worker.submit(self._set_radio(enabled),
                            lambda r, e: self.wifiResult.emit(r if e is None else {"ok": False, "error": str(e)}))

    async def _set_radio(self, enabled: bool) -> dict:
        from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
        access = await Radio.request_access_async()
        if access != RadioAccessStatus.ALLOWED:
            return {"ok": False, "error": "Windows did not allow radio control.", "settings": "wifi"}
        radios = await Radio.get_radios_async()
        for r in radios:
            if r.kind == RadioKind.WI_FI:
                status = await r.set_state_async(RadioState.ON if enabled else RadioState.OFF)
                ok = status == RadioAccessStatus.ALLOWED
                return {"ok": ok, "radio": enabled, "error": "" if ok else "Windows refused the change.",
                        **({} if ok else {"settings": "wifi"})}
        return {"ok": False, "error": "No Wi-Fi radio found.", "settings": "wifi"}
