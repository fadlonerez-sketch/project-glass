"""GlassController -- the object QML sees as ``glass``: theme, material, settings, Dynamic Glass state, media,
system status, weather, notifications and Garvis activity, plus every action the Shell UI can take."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from PySide6.QtCore import Property, QObject, QRect, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication, QRegion, QWindow

from glass.core import launchdeck, material, paths, theme
from glass.core.settings import SettingsStore
from glass.core.states import DynamicGlassMachine, HoverArming
from glass.core.weather import OpenMeteo, WeatherError
from glass.win import display
from glass.win.audio import AudioService
from glass.win.media import MediaService
from glass.win.notifications import NotificationMirror
from glass.win.system import NetworkService, PowerService, open_settings_page

log = logging.getLogger(__name__)

PRIORITY = {"low": 0, "normal": 1, "high": 2}


class GlassController(QObject):
    themeChanged = Signal()
    settingsChanged = Signal()
    materialChanged = Signal()
    stateChanged = Signal()
    mediaChanged = Signal()
    powerChanged = Signal()
    networkChanged = Signal()
    audioChanged = Signal()
    brightnessChanged = Signal()
    weatherChanged = Signal()
    notificationsChanged = Signal()
    garvisChanged = Signal()
    wifiChanged = Signal()
    backdropChanged = Signal()
    statusTextChanged = Signal()
    toast = Signal(str)
    closeOverlays = Signal()
    requestControlCenter = Signal(str)
    requestRestore = Signal()
    requestQuit = Signal()
    requestRevealTray = Signal()
    requestPower = Signal(bool)
    poweredChanged = Signal()
    islandChanged = Signal()
    _weatherResult = Signal(object, str)

    def __init__(self, settings: SettingsStore, parent=None):
        super().__init__(parent)
        self.store = settings
        self._settings = settings.all()
        self._system_dark = False
        self._theme = theme.tokens(self._settings, self._system_dark)
        self._material = material.uniforms(self._settings, self._theme)
        s = self._settings
        self.machine = DynamicGlassMachine(s["topbar.media.expand_delay_ms"] / 1000, s["topbar.media.collapse_delay_ms"] / 1000)
        self._state = "idle"
        self._payload: dict = {}
        self._arming = HoverArming()
        self._powered = True
        self._power_busy = False
        self._island_screen = ""
        self._tick = QTimer(self, singleShot=True)
        self._tick.timeout.connect(self._resolve)
        self._media: dict = {"present": False}
        self._power: dict = {}
        self._network: dict = {}
        self._audio: dict = {}
        self._brightness = -1
        self._weather: dict = {}
        self._notifications: list[dict] = []
        self._garvis: dict = {"engine": False, "active": False, "stopped": False, "app": ""}
        self._wifi_networks: list = []
        self._wifi_status: dict = {}
        self._backdrops: dict[str, str] = {}
        self._mirror_status = "unavailable"
        self._audio_ready = False

        self.media_service = MediaService(self)
        self.power_service = PowerService(self)
        self.network_service = NetworkService(self)
        self.audio_service = AudioService(self)
        self.mirror = NotificationMirror(self)
        self.weather_client = OpenMeteo(cache_path=paths.cache_dir() / "weather.json")
        self._weather_timer = QTimer(self, interval=20 * 60 * 1000)
        self._weather_timer.timeout.connect(self.refreshWeather)
        self._weatherResult.connect(self._on_weather)
        self.artwork = None  # BytesImageProvider, attached by the app

        self.media_service.changed.connect(self._on_media)
        self.media_service.artworkReady.connect(self._on_artwork)
        self.power_service.changed.connect(self._on_power)
        self.network_service.changed.connect(self._on_network)
        self.network_service.wifiNetworks.connect(self._on_wifi_networks)
        self.network_service.wifiResult.connect(self._on_wifi_result)
        self.audio_service.changed.connect(self._on_audio)
        self.mirror.notification.connect(self._on_windows_notification)
        self.mirror.statusChanged.connect(self._on_mirror_status)
        settings.subscribe(lambda changed: QTimer.singleShot(0, lambda: self._on_settings(changed)))

    # ------------------------------------------------------------------ startup
    def start(self) -> None:
        self.media_service.start()
        self.power_service.start()
        self.network_service.start()
        self.audio_service.start()
        if self._settings["notifications.mirror_windows"]:
            self.mirror.start()
        self._brightness = display.get_brightness() if display else None
        self._brightness = -1 if self._brightness is None else self._brightness
        self.brightnessChanged.emit()
        self.refreshWeather()
        self._weather_timer.start()
        self._resolve()

    _paused = False

    def pause_services(self) -> None:
        """Glass is off: stop the periodic work only the visible surfaces need (event subscriptions stay, idle)."""
        self._paused = True
        self._weather_timer.stop()
        self.mirror.stop()
        self.machine.hover.cancel()

    def resume_services(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self.refreshWeather()
        self._weather_timer.start()
        if self._settings["notifications.mirror_windows"]:
            self.mirror.start()

    def set_system_dark(self, dark: bool) -> None:
        if dark != self._system_dark:
            self._system_dark = dark
            self._retheme()

    def _retheme(self) -> None:
        self._theme = theme.tokens(self._settings, self._system_dark)
        self._material = material.uniforms(self._settings, self._theme)
        try:
            theme.write_theme_file(paths.theme_file(), self._theme)
        except OSError as exc:
            log.warning("theme.json not written: %s", exc)
        self.themeChanged.emit()
        self.materialChanged.emit()

    def _on_settings(self, changed: dict) -> None:
        self._settings.update(changed)
        self.settingsChanged.emit()
        if any(k.startswith(("appearance.", "glass.")) for k in changed):
            self._retheme()
        if "topbar.media.expand_delay_ms" in changed or "topbar.media.collapse_delay_ms" in changed:
            self.machine.hover.expand_delay = self._settings["topbar.media.expand_delay_ms"] / 1000
            self.machine.hover.collapse_delay = self._settings["topbar.media.collapse_delay_ms"] / 1000
        if any(k.startswith("weather.") for k in changed):
            self.refreshWeather()
        if "notifications.mirror_windows" in changed:
            (self.mirror.start if changed["notifications.mirror_windows"] else self.mirror.stop)()
        self.machine.set(media_enabled=self._settings["topbar.media.enabled"],
                         hover_expand_enabled=self._settings["topbar.media.hover_expand"])
        self._resolve()

    # ------------------------------------------------------------------ properties
    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        return self._theme

    @Property("QVariantMap", notify=materialChanged)
    def material(self):
        return self._material

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property("QVariantMap", notify=stateChanged)
    def statePayload(self):
        return self._payload

    @Property("QVariantMap", notify=mediaChanged)
    def media(self):
        return self._media

    @Property("QVariantMap", notify=powerChanged)
    def power(self):
        return self._power

    @Property("QVariantMap", notify=networkChanged)
    def network(self):
        return self._network

    @Property("QVariantMap", notify=audioChanged)
    def audio(self):
        return self._audio

    @Property(int, notify=brightnessChanged)
    def brightness(self):
        return self._brightness

    @Property("QVariantMap", notify=weatherChanged)
    def weather(self):
        return self._weather

    @Property("QVariantList", notify=notificationsChanged)
    def notifications(self):
        return self._notifications

    @Property("QVariantMap", notify=garvisChanged)
    def garvis(self):
        return self._garvis

    @Property("QVariantList", notify=wifiChanged)
    def wifiNetworks(self):
        return self._wifi_networks

    @Property("QVariantMap", notify=wifiChanged)
    def wifiStatus(self):
        return self._wifi_status

    @Property("QVariantMap", notify=backdropChanged)
    def backdrops(self):
        return self._backdrops

    @Property(str, notify=notificationsChanged)
    def mirrorStatus(self):
        return self._mirror_status

    @Property(bool, notify=poweredChanged)
    def powered(self):
        """The real state of Glass (surfaces shown, space reserved, taskbar replaced), not a requested one."""
        return self._powered

    @Property(bool, notify=poweredChanged)
    def powerBusy(self):
        return self._power_busy

    def set_powered(self, on: bool, busy: bool = False) -> None:
        if on != self._powered or busy != self._power_busy:
            self._powered, self._power_busy = on, busy
            self.poweredChanged.emit()

    @Slot(bool)
    def setPower(self, on: bool):
        self.closeAll()
        self.requestPower.emit(bool(on))

    @Property(str, notify=islandChanged)
    def islandScreen(self):
        """The display whose top bar hosts the Dynamic Glass (the active display, or the primary one)."""
        return self._island_screen

    def set_island_screen(self, name: str) -> None:
        if name != self._island_screen:
            self._island_screen = name
            self.machine.hover.cancel()
            self.islandChanged.emit()
            self._resolve()

    # ------------------------------------------------------------------ Dynamic Glass state
    @staticmethod
    def _cursor() -> tuple[int, int]:
        p = QCursor.pos()
        return p.x(), p.y()

    def _resolve(self) -> None:
        now = time.monotonic()
        r = self.machine.resolve(now)
        if r.state.value != self._state or r.payload != self._payload:
            if r.state.value != self._state:
                self._arming.shape_changed(self._cursor(), now)
            self._state = r.state.value
            self._payload = dict(r.payload)
            self.stateChanged.emit()
        nxt = self.machine.next_deadline()
        if nxt is not None:
            self._tick.start(max(5, int((nxt - now) * 1000) + 5))

    @Slot()
    def pillEnter(self):
        now = time.monotonic()
        if self._arming.enter(self._cursor(), now):
            self.machine.pointer_enter(now)
            self._resolve()

    @Slot()
    def pillMove(self):
        """The pointer moved inside the pill: a hover that began under a resting pointer now counts."""
        if self._arming.pending and self._arming.move(self._cursor()):
            self.machine.pointer_enter(time.monotonic())
            self._resolve()

    @Slot()
    def pillLeave(self):
        self._arming.leave()
        self.machine.pointer_leave(time.monotonic())
        self._resolve()

    @Property(bool, notify=stateChanged)
    def pillArmPending(self):
        return self._arming.pending

    @Slot()
    def pillClick(self):
        if self._state == "notification":
            self.machine.dismiss_notification()
        self.machine.click()
        self._resolve()

    @Slot(bool)
    def setControlCenterOpen(self, open_: bool):
        self.machine.set(control_center_open=open_)
        self._resolve()

    @Slot(bool)
    def setControlsOpen(self, open_: bool):
        self.machine.set(controls_open=open_)
        self._resolve()

    @Slot()
    def closeAll(self):
        self.machine.set(control_center_open=False, controls_open=False)
        self.machine.hover.cancel()
        self._resolve()
        self.closeOverlays.emit()

    def activity(self, payload: dict, duration: float = 1.6) -> None:
        self.machine.activity(payload, duration, now=time.monotonic())
        self._resolve()

    # ------------------------------------------------------------------ media
    def _on_media(self, st: dict) -> None:
        if self._media.get("artwork") and "artwork" not in st:
            st["artwork"] = self._media["artwork"]
        st["artworkUrl"] = f"image://artwork/{st['artwork']}" if st.get("artwork") else ""
        app_id = st.get("app_id", "")
        st["appName"] = self._app_name(app_id)
        self._media = st
        self.machine.set(media_present=bool(st.get("present") and (st.get("title") or st.get("playing"))),
                         media_playing=bool(st.get("playing")))
        self.mediaChanged.emit()
        self._resolve()

    def _app_name(self, app_id: str) -> str:
        if not app_id:
            return ""
        low = app_id.lower()
        known = {"spotify.exe": "Spotify", "chrome": "Chrome", "msedge": "Edge", "brave": "Brave",
                 "firefox": "Firefox"}
        for k, v in known.items():
            if low.startswith(k):
                return v
        name = self.app_name_lookup(app_id) if self.app_name_lookup else ""
        return name or app_id.split("!")[0].split("_")[0].split(".")[-1]

    app_name_lookup = None  # set by the app: aumid -> display name via the catalog

    def _on_artwork(self, ident: str, data: bytes) -> None:
        if self.artwork is not None:
            self.artwork.put(ident, data)

    @Slot()
    def playPause(self):
        self.media_service.play_pause()

    @Slot()
    def nextTrack(self):
        self.media_service.next()

    @Slot()
    def previousTrack(self):
        self.media_service.previous()

    @Slot(float)
    def seek(self, seconds: float):
        self.media_service.seek(seconds)

    # ------------------------------------------------------------------ system status
    def _on_power(self, st: dict) -> None:
        old = self._power
        self._power = st
        self.powerChanged.emit()
        if old and old.get("plugged") != st.get("plugged"):
            self.activity({"kind": "power", "plugged": st.get("plugged"), "percent": st.get("percent")}, 2.2)
        elif old and st.get("percent") in (20, 10, 5) and old.get("percent") != st.get("percent") and not st.get("plugged"):
            self.activity({"kind": "battery_low", "percent": st.get("percent")}, 3.0)

    def _on_network(self, st: dict) -> None:
        old = self._network
        self._network = st
        self.networkChanged.emit()
        if old and (old.get("internet"), old.get("ssid")) != (st.get("internet"), st.get("ssid")):
            self.activity({"kind": "network", "internet": st.get("internet"), "name": st.get("ssid") or st.get("name"),
                           "type": st.get("kind")}, 2.0)

    def _on_audio(self, st: dict) -> None:
        old = self._audio
        self._audio = st
        self.audioChanged.emit()
        if self._audio_ready and old and (abs(old.get("volume", 0) - st.get("volume", 0)) > 0.004 or old.get("muted") != st.get("muted")):
            if self._state not in ("control_center", "controls"):
                self.activity({"kind": "volume", "level": st.get("volume", 0), "muted": st.get("muted")}, 1.4)
        self._audio_ready = True

    @Slot(float)
    def setVolume(self, level: float):
        self.audio_service.set_volume(level)

    @Slot(bool)
    def setMuted(self, muted: bool):
        self.audio_service.set_muted(muted)

    @Slot(int)
    def setBrightness(self, level: int):
        if self._brightness < 0:
            return
        self._brightness = int(level)
        self.brightnessChanged.emit()
        threading.Thread(target=display.set_brightness, args=(int(level),), daemon=True).start()

    @Slot()
    def scanWifi(self):
        self._wifi_status = {"scanning": True}
        self.wifiChanged.emit()
        self.network_service.scan_wifi()

    def _on_wifi_networks(self, nets: list) -> None:
        if nets and "error" in nets[0]:
            self._wifi_status = {"scanning": False, "error": nets[0]["error"]}
            self._wifi_networks = []
        else:
            self._wifi_status = {"scanning": False}
            self._wifi_networks = nets
        self.wifiChanged.emit()

    @Slot(str, str)
    def connectWifi(self, ssid: str, password: str):
        self._wifi_status = {"connecting": ssid}
        self.wifiChanged.emit()
        self.network_service.connect_wifi(ssid, password)

    @Slot(bool)
    def setWifiEnabled(self, enabled: bool):
        self.network_service.set_wifi_enabled(enabled)

    def _on_wifi_result(self, res: dict) -> None:
        self._wifi_status = {"result": res}
        self.wifiChanged.emit()
        if not res.get("ok") and res.get("settings"):
            open_settings_page(res["settings"])

    @Slot(str)
    def openSettingsPage(self, name: str):
        self.closeAll()
        if not open_settings_page(name):
            self.toast.emit("Windows Settings could not be opened.")

    # ------------------------------------------------------------------ weather
    @Slot()
    def refreshWeather(self):
        s = self._settings
        if not s["weather.enabled"]:
            self._weather = {"enabled": False}
            self.weatherChanged.emit()
            return
        lat, lon = s.get("weather.latitude"), s.get("weather.longitude")
        if lat is None or lon is None:
            self._weather = {"enabled": True, "needsSetup": True}
            self.weatherChanged.emit()
            return
        units, label = s["weather.units"], s["weather.label"] or s["weather.city"]

        def work():
            try:
                rep = self.weather_client.forecast(lat, lon, units, label)
                self._weatherResult.emit(rep.to_dict(), "")
            except WeatherError as exc:
                self._weatherResult.emit(None, str(exc))
        threading.Thread(target=work, name="glass-weather", daemon=True).start()

    def _on_weather(self, report, error: str) -> None:
        if report:
            self._weather = {"enabled": True, **report}
        else:
            self._weather = {**self._weather, "enabled": True, "error": error}
        self.weatherChanged.emit()

    # ------------------------------------------------------------------ notifications
    def notify(self, payload: dict, priority: str = "normal") -> None:
        s = self._settings
        app_rules = (s.get("notifications.apps") or {}).get(payload.get("app_id") or payload.get("app", ""), {})
        if app_rules.get("enabled") is False:
            return
        prio = app_rules.get("priority", priority)
        entry = {**payload, "time": payload.get("time", time.time()), "priority": prio}
        self._notifications.insert(0, entry)
        del self._notifications[50:]
        self.notificationsChanged.emit()
        if not s["notifications.enabled"] or not s["topbar.notifications.enabled"]:
            return
        if s["notifications.dnd"] and prio != "high":
            return
        if PRIORITY.get(prio, 1) < PRIORITY.get(s["notifications.min_priority"], 1):
            return
        if s["notifications.presentation"] == "silent" or app_rules.get("show") == "silent":
            return
        self.machine.notify(entry, float(s["topbar.notifications.duration_s"]), PRIORITY.get(prio, 1))
        self._resolve()

    def _on_windows_notification(self, n: dict) -> None:
        self.notify(n)

    def _on_mirror_status(self, status: str) -> None:
        self._mirror_status = status
        self.notificationsChanged.emit()

    @Slot()
    def dismissNotification(self):
        self.machine.dismiss_notification()
        self._resolve()

    @Slot()
    def clearNotifications(self):
        self._notifications = []
        self.notificationsChanged.emit()

    # ------------------------------------------------------------------ Garvis / engine (wired by the app)
    def set_garvis(self, **changes) -> None:
        self._garvis = {**self._garvis, **changes}
        self.machine.set(garvis_active=bool(self._garvis.get("active") and not self._garvis.get("stopped")
                                            and self._settings["garvis.indicator"]))
        self.garvisChanged.emit()
        self._resolve()

    emergency_stop_handler = None
    resume_handler = None

    @Slot()
    def emergencyStop(self):
        if self.emergency_stop_handler:
            self.emergency_stop_handler()

    @Slot()
    def resumeControl(self):
        if self.resume_handler:
            self.resume_handler()

    # ------------------------------------------------------------------ shell actions
    @Slot(str, "QVariant")
    def setSetting(self, key: str, value):
        res = self.store.patch({key: value})
        if res.errors:
            self.toast.emit(next(iter(res.errors.values())))

    @Slot(str)
    def openControlCenter(self, page: str = ""):
        self.closeAll()
        self.requestControlCenter.emit(page)

    @Slot()
    def openLauncher(self):
        self.closeAll()
        if not launchdeck.send("launcher"):
            if not launchdeck.send("show"):
                self.toast.emit("LaunchDeck isn't running.")

    @Slot()
    def revealTray(self):
        self.closeAll()
        self.requestRevealTray.emit()

    @Slot()
    def restoreWindowsDesktop(self):
        self.requestRestore.emit()

    @Slot()
    def quitGlass(self):
        self.requestQuit.emit()

    def set_backdrops(self, mapping: dict[str, str]) -> None:
        self._backdrops = mapping
        self.backdropChanged.emit()

    # ------------------------------------------------------------------ window helpers for QML
    @Slot(QObject, "QVariantList")
    def setInteractiveRegion(self, window, rects):
        """Only these rectangles of a Glass window take mouse input; everything else clicks through."""
        if not isinstance(window, QWindow):
            return
        region = QRegion()
        for r in rects:
            try:
                x, y, w, h = (int(round(float(v))) for v in (r["x"], r["y"], r["width"], r["height"]))
            except (KeyError, TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                region = region.united(QRegion(QRect(x, y, w, h)))
        window.setMask(region if not region.isEmpty() else QRegion(QRect(0, 0, 1, 1)))

    @Slot(QObject, bool)
    def requestKeyboard(self, window, wanted: bool):
        """Text fields in flyouts need keyboard focus; Glass windows otherwise never take focus."""
        from PySide6.QtCore import Qt
        if not isinstance(window, QWindow):
            return
        window.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not wanted)
        if wanted:
            window.requestActivate()

    @Slot(str, result=str)
    def formatDuration(self, seconds) -> str:
        try:
            s = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return "0:00"
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
