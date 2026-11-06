"""The Control Center's link to the Shell (settings, dock, status) and the automation engine (Garvis
permissions, audit log, emergency stop). Both over authenticated local pipes.

Settings are owned by the Shell. If the Shell isn't running, the Control Center edits the same store
directly so changes still persist; they take effect when Glass starts.
"""
from __future__ import annotations

import itertools
import logging
import time
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalSocket

from glass.core import colors, ipc, material, paths, security, theme
from glass.core.settings import SPECS, SettingsStore

log = logging.getLogger(__name__)


class ShellLink(QObject):
    """Event-driven client of the Shell API (same framing as every Glass pipe)."""
    connectedChanged = Signal(bool)
    notification = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sock = QLocalSocket(self)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.readyRead.connect(self._on_ready)
        self.sock.errorOccurred.connect(lambda *_: self._schedule())
        self._dec = ipc.FrameDecoder()
        self._ids = itertools.count(1)
        self._cbs: dict[int, Callable] = {}
        self.ready = False
        self._retry = QTimer(self, singleShot=True, interval=1500)
        self._retry.timeout.connect(self.start)

    def start(self) -> None:
        if self.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.sock.connectToServer(security.pipe_name("Shell"))

    def _schedule(self) -> None:
        if not self._retry.isActive():
            self._retry.start()

    def _on_connected(self) -> None:
        def hello(res, err):
            self.ready = err is None
            if err:
                log.warning("Shell refused the Control Center: %s", err)
            self.connectedChanged.emit(self.ready)
        self._send("hello", {"protocol": ipc.PROTOCOL_VERSION, "client": "controlcenter",
                             "token": security.read_secret("owner") or ""}, hello, force=True)

    def _on_disconnected(self) -> None:
        self.ready = False
        self._dec = ipc.FrameDecoder()
        for cb in self._cbs.values():
            cb(None, {"code": "unavailable", "message": "Glass is not running"})
        self._cbs.clear()
        self.connectedChanged.emit(False)
        self._schedule()

    def _on_ready(self) -> None:
        try:
            msgs = self._dec.feed(bytes(self.sock.readAll()))
        except ipc.ProtocolError:
            self.sock.abort()
            return
        for m in msgs:
            if "id" in m and m["id"] in self._cbs:
                cb = self._cbs.pop(m["id"])
                cb(m.get("result"), m.get("error"))
            elif "method" in m:
                self.notification.emit(m["method"], m.get("params") or {})

    def _send(self, method: str, params: dict, cb: Callable | None, force: bool = False) -> None:
        if not force and not self.ready:
            if cb:
                cb(None, {"code": "unavailable", "message": "Glass is not running"})
            return
        mid = next(self._ids)
        self._cbs[mid] = cb or (lambda r, e: None)
        self.sock.write(ipc.encode(ipc.request(mid, method, params)))

    def call(self, method: str, params: dict | None = None, cb: Callable | None = None) -> None:
        self._send(method, params or {}, cb)


class ControlCenterBridge(QObject):
    settingsChanged = Signal()
    themeChanged = Signal()
    statusChanged = Signal()
    appsChanged = Signal()
    catalogChanged = Signal()
    placesChanged = Signal()
    garvisChanged = Signal()
    auditChanged = Signal()
    connectionChanged = Signal()
    message = Signal(str)
    pageRequested = Signal(str)
    marketsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shell = ShellLink(self)
        self.shell.connectedChanged.connect(self._on_shell)
        self.shell.notification.connect(self._on_shell_event)
        self._local: SettingsStore | None = None
        self._settings: dict[str, Any] = {}
        self._theme: dict[str, Any] = {}
        self._material: dict[str, Any] = {}
        self._status: dict[str, Any] = {}
        self._apps: list = []
        self._catalog: list = []
        self._places: list = []
        self._perm: dict = {}
        self._audit: list = []
        self._engine_ok = False
        self._market_results: list = []
        self._markets: dict = {}
        self._system_dark = False
        self.engine = None
        self._load_local()

    # ------------------------------------------------------------------ startup
    def start(self, system_dark: bool) -> None:
        self._system_dark = system_dark
        self._retheme_local()
        self.shell.start()
        try:
            from glass.automation.qtclient import EngineClient
            self.engine = EngineClient(client_name="owner", subscribe_admin=True, parent=self)
            self.engine.connectedChanged.connect(self._on_engine)
            self.engine.notification.connect(self._on_engine_event)
            self.engine.start()
        except Exception as exc:
            log.warning("engine client unavailable: %s", exc)

    def _load_local(self) -> None:
        self._local = SettingsStore(paths.settings_db())
        self._settings = self._local.all()

    def set_system_dark(self, dark: bool) -> None:
        self._system_dark = dark
        if not self.shell.ready:
            self._retheme_local()

    def _retheme_local(self) -> None:
        self._theme = theme.tokens(self._settings, self._system_dark)
        self._material = material.uniforms(self._settings, self._theme)
        self.themeChanged.emit()

    # ------------------------------------------------------------------ shell events
    def _on_shell(self, ok: bool) -> None:
        self.connectionChanged.emit()
        if ok:
            self.shell.call("settings.get", {}, lambda r, e: r and self._apply_settings(r["values"]))
            self.shell.call("theme.get", {}, lambda r, e: r and self._apply_theme(r))
            self.refreshStatus()
            self.refreshApps()
            self.searchCatalog("")
            self.refreshMarkets()

    def _on_shell_event(self, method: str, params: dict) -> None:
        if method == "settings.changed":
            changed = params.get("changed") or {}
            self._settings.update(changed)
            self.settingsChanged.emit()
            if any(k.startswith("markets.") for k in changed):
                QTimer.singleShot(1500, self.refreshMarkets)
        elif method == "power.changed":
            self._status = {**self._status, "powered": bool(params.get("powered")), "power_busy": bool(params.get("busy"))}
            self.statusChanged.emit()
        elif method == "theme.changed":
            self._apply_theme(params)

    def _apply_settings(self, values: dict) -> None:
        self._settings = values
        self.settingsChanged.emit()

    def _apply_theme(self, r: dict) -> None:
        self._theme = r.get("theme") or self._theme
        self._material = r.get("material") or self._material
        self.themeChanged.emit()

    # ------------------------------------------------------------------ properties
    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        return self._theme

    @Property("QVariantMap", notify=themeChanged)
    def material(self):
        return self._material

    @Property("QVariantMap", notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=connectionChanged)
    def shellConnected(self):
        return self.shell.ready

    @Property(bool, notify=garvisChanged)
    def engineConnected(self):
        return self._engine_ok

    @Property("QVariantList", notify=appsChanged)
    def apps(self):
        return self._apps

    @Property("QVariantList", notify=catalogChanged)
    def catalog(self):
        return self._catalog

    @Property("QVariantList", notify=placesChanged)
    def places(self):
        return self._places

    @Property("QVariantMap", notify=garvisChanged)
    def permissions(self):
        return self._perm

    @Property("QVariantList", notify=auditChanged)
    def audit(self):
        return self._audit

    @Property("QVariantList", constant=True)
    def presets(self):
        return [{"name": n, "hex": h} for n, h in colors.PRESETS]

    # ------------------------------------------------------------------ settings
    @Slot(str, "QVariant")
    def set(self, key: str, value) -> None:
        if key not in SPECS:
            self.message.emit(f"Unknown setting {key}")
            return
        if self.shell.ready:
            self.shell.call("settings.patch", {"values": {key: value}}, self._after_patch)
        else:
            res = self._local.patch({key: value})
            self._after_patch({"changed": res.changed, "errors": res.errors}, None)

    def _after_patch(self, res, err) -> None:
        if err:
            self.message.emit(err.get("message", "Could not save"))
            return
        if res.get("errors"):
            self.message.emit(next(iter(res["errors"].values())))
        if res.get("changed"):
            self._settings.update(res["changed"])
            self.settingsChanged.emit()
            if not self.shell.ready:
                self._retheme_local()

    @Slot(str)
    def resetSection(self, section: str) -> None:
        if self.shell.ready:
            self.shell.call("settings.reset", {"section": section}, lambda r, e: r and self._after_patch(r, e))
        else:
            res = self._local.reset(section=section)
            self._after_patch({"changed": res.changed}, None)

    @Slot("QVariantList")
    def resetKeys(self, keys) -> None:
        keys = [str(k) for k in keys]
        if self.shell.ready:
            self.shell.call("settings.reset", {"keys": keys}, lambda r, e: r and self._after_patch(r, e))
        else:
            res = self._local.reset(keys=keys)
            self._after_patch({"changed": res.changed}, None)

    # ------------------------------------------------------------------ colours
    @Slot(str, result=bool)
    def isHex(self, text: str) -> bool:
        return colors.is_hex(text)

    @Slot(str, result=str)
    def normalizeHex(self, text: str) -> str:
        try:
            return colors.parse_hex(text)
        except colors.ColorError:
            return ""

    @Slot(int, int, int, result=str)
    def rgbToHex(self, r: int, g: int, b: int) -> str:
        try:
            return colors.from_rgb(r, g, b)
        except colors.ColorError:
            return ""

    @Slot(str, result="QVariantList")
    def hexToRgb(self, h: str) -> list:
        try:
            return list(colors.to_rgb(h))
        except colors.ColorError:
            return [0, 0, 0]

    @Slot(str, result="QVariantList")
    def hexToHsv(self, h: str) -> list:
        try:
            return list(colors.to_hsv(h))
        except colors.ColorError:
            return [0, 0, 0]

    @Slot(float, float, float, result=str)
    def hsvToHex(self, h: float, s: float, v: float) -> str:
        return colors.from_hsv(h, s, v)

    @Slot(str)
    def saveColor(self, h: str) -> None:
        saved = list(self._settings.get("appearance.saved_colors") or [])
        h = self.normalizeHex(h)
        if h and h not in saved:
            self.set("appearance.saved_colors", (saved + [h])[-24:])

    @Slot(str)
    def forgetColor(self, h: str) -> None:
        saved = [c for c in (self._settings.get("appearance.saved_colors") or []) if c != h]
        self.set("appearance.saved_colors", saved)

    @Slot(str, result="QVariantMap")
    def previewTheme(self, accent: str) -> dict:
        """Theme tokens for a draft accent, so pickers can preview before Apply."""
        vals = dict(self._settings)
        if colors.is_hex(accent):
            vals["appearance.accent"] = accent
        return theme.tokens(vals, self._system_dark if self._settings.get("appearance.theme") == "adaptive"
                            else self._settings.get("appearance.theme") == "dark")

    # ------------------------------------------------------------------ dock & catalog
    @Slot()
    def refreshApps(self) -> None:
        self.shell.call("dock.apps", {}, lambda r, e: r and self._set("_apps", r["apps"], self.appsChanged))

    @Slot(str, str)
    def dockOp(self, op: str, app_id: str) -> None:
        self.shell.call("dock.op", {"op": op, "app_id": app_id}, lambda r, e: (self._report(e), self.refreshApps()))

    @Slot(str, int)
    def movePinned(self, app_id: str, index: int) -> None:
        self.shell.call("dock.op", {"op": "move", "app_id": app_id, "index": index}, lambda r, e: (self._report(e), self.refreshApps()))

    @Slot(str)
    def addApp(self, parsing: str) -> None:
        def done(r, e):
            self._report(e)
            if r and not r.get("ok"):
                self.message.emit(r.get("error", "Could not add the app"))
            elif r:
                self.message.emit("Added to the Dock")
            self.refreshApps()
        self.shell.call("dock.op", {"op": "add", "parsing": parsing}, done)

    @Slot(str)
    def searchCatalog(self, text: str) -> None:
        self.shell.call("catalog.search", {"text": text}, lambda r, e: r is not None and self._set("_catalog", r, self.catalogChanged))

    # ------------------------------------------------------------------ weather
    @Slot(str)
    def searchCity(self, query: str) -> None:
        if len(query.strip()) < 2:
            self._set("_places", [], self.placesChanged)
            return
        if self.shell.ready:
            self.shell.call("weather.search", {"query": query}, lambda r, e: (self._report(e), r and self._set("_places", r["places"], self.placesChanged)))
        else:
            from glass.core.weather import OpenMeteo
            try:
                places = OpenMeteo().search(query)
                self._set("_places", [{"name": p.name, "label": p.label, "latitude": p.latitude, "longitude": p.longitude}
                                      for p in places], self.placesChanged)
            except Exception as exc:
                self.message.emit(str(exc))

    @Slot("QVariantMap")
    def chooseCity(self, place) -> None:
        for k, v in (("weather.city", place.get("name", "")), ("weather.label", place.get("label", "")),
                     ("weather.latitude", place.get("latitude")), ("weather.longitude", place.get("longitude"))):
            self.set(k, v)
        self._set("_places", [], self.placesChanged)

    # ------------------------------------------------------------------ Liquid Glass presets
    @Property("QVariantList", constant=True)
    def glassPresets(self):
        about = {"subtle": "Quiet frosted glass with gentle highlights.",
                 "liquid": "Fluid lensing at the edges over a softer blur.",
                 "crystal": "Clear, brilliant and deep: every effect at full strength."}
        return [{"key": k, "name": material.PRESET_NAMES[k], "about": about[k]} for k in material.PRESETS]

    @Slot(str, result="QVariantMap")
    def presetMaterial(self, name: str) -> dict:
        """Shader uniforms for a preset with the current theme and accent: what its live preview renders."""
        values = {**self._settings, **material.PRESETS.get(name, {})}
        return material.uniforms(values, self._theme or theme.tokens(values, self._system_dark))

    @Slot(str)
    def applyPreset(self, name: str) -> None:
        preset = material.PRESETS.get(name)
        if not preset:
            return
        if self.shell.ready:
            self.shell.call("settings.patch", {"values": dict(preset)}, self._after_patch)
        else:
            res = self._local.patch(dict(preset))
            self._after_patch({"changed": res.changed, "errors": res.errors}, None)

    @Property(str, notify=settingsChanged)
    def currentPreset(self):
        return material.matching_preset(self._settings)

    # ------------------------------------------------------------------ power
    @Property(bool, notify=statusChanged)
    def powered(self):
        """Glass's real state as the Shell reports it (not the requested one)."""
        return bool(self._status.get("powered")) and self.shell.ready

    @Property(bool, notify=statusChanged)
    def powerBusy(self):
        return bool(self._status.get("power_busy"))

    @Slot(bool)
    def setPower(self, on: bool) -> None:
        if not self.shell.ready:
            if on:
                self.startGlass()
            return
        self._status = {**self._status, "power_busy": True}
        self.statusChanged.emit()
        self.shell.call("shell.command", {"command": "power_on" if on else "power_off"},
                        lambda r, e: (self._report(e), QTimer.singleShot(400, self.refreshStatus)))

    # ------------------------------------------------------------------ markets
    @Property("QVariantList", notify=marketsChanged)
    def marketResults(self):
        return self._market_results

    @Property("QVariantMap", notify=marketsChanged)
    def markets(self):
        return self._markets

    @Slot()
    def refreshMarkets(self) -> None:
        if self.shell.ready:
            self.shell.call("markets.get", {}, lambda r, e: r is not None and self._set("_markets", r, self.marketsChanged))

    @Slot(str)
    def searchMarkets(self, text: str) -> None:
        if len(text.strip()) < 1:
            self._set("_market_results", [], self.marketsChanged)
            return
        if self.shell.ready:
            self.shell.call("markets.search", {"query": text},
                            lambda r, e: (self._report(e), r and self._set("_market_results", r["results"], self.marketsChanged)))
        else:
            from glass.core.markets import MarketError, YahooFinance
            try:
                self._set("_market_results", YahooFinance().search(text), self.marketsChanged)
            except MarketError as exc:
                self.message.emit(str(exc))

    @Slot(str, str)
    def addSymbol(self, key: str, symbol: str) -> None:
        current = list(self._settings.get(key) or [])
        if symbol.upper() in current:
            self.message.emit(f"{symbol.upper()} is already in the list")
            return
        self.set(key, current + [symbol])
        self._set("_market_results", [], self.marketsChanged)

    @Slot(str, str)
    def removeSymbol(self, key: str, symbol: str) -> None:
        self.set(key, [x for x in (self._settings.get(key) or []) if x != symbol])

    @Slot(str, str, int)
    def moveSymbol(self, key: str, symbol: str, delta: int) -> None:
        items = list(self._settings.get(key) or [])
        if symbol not in items:
            return
        i = items.index(symbol)
        j = max(0, min(len(items) - 1, i + delta))
        items.insert(j, items.pop(i))
        self.set(key, items)

    # ------------------------------------------------------------------ status & system
    @Slot()
    def refreshStatus(self) -> None:
        self.shell.call("status.get", {}, lambda r, e: r and self._set("_status", r, self.statusChanged))

    @Slot(str)
    def shellCommand(self, command: str) -> None:
        self.shell.call("shell.command", {"command": command}, lambda r, e: (self._report(e), self.refreshStatus()))

    @Slot(str)
    def openSettingsPage(self, name: str) -> None:
        from glass.win.system import open_settings_page
        open_settings_page(name)

    @Slot()
    def startGlass(self) -> None:
        import subprocess, sys
        from pathlib import Path
        exe = Path(sys.executable)
        pyw = exe.parent / "pythonw.exe"
        subprocess.Popen([str(pyw if pyw.exists() else exe), "-m", "glass.shell"], cwd=str(paths.PROJECT_DIR),
                         creationflags=subprocess.DETACHED_PROCESS)
        self.message.emit("Starting Project Glass…")

    @Slot()
    def restoreWindows(self) -> None:
        import subprocess, sys
        subprocess.Popen([sys.executable, "-m", "glass.recovery", "--restore"], cwd=str(paths.PROJECT_DIR),
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.message.emit("Restoring the Windows desktop…")

    @Slot(str)
    def launchdeck(self, what: str) -> None:
        from glass.core import launchdeck
        if not launchdeck.send(what):
            self.message.emit("LaunchDeck isn't running.")

    @Slot(result=bool)
    def launchdeckInstalled(self) -> bool:
        from glass.core import launchdeck
        return launchdeck.is_installed()

    @Slot(result=str)
    def dataDir(self) -> str:
        return str(paths.data_dir())

    @Slot()
    def openDataDir(self) -> None:
        import os
        os.startfile(str(paths.data_dir()))

    @Slot(result=str)
    def notificationIdentityHelp(self) -> str:
        return str(paths.PROJECT_DIR / "docs" / "NOTIFICATIONS.md")

    # ------------------------------------------------------------------ Garvis (engine, owner token)
    def _on_engine(self, ok: bool) -> None:
        self._engine_ok = bool(ok)
        self.garvisChanged.emit()
        if ok:
            self.refreshPermissions()
            self.refreshAudit()

    def _on_engine_event(self, method: str, params) -> None:
        if method in ("activity", "stopped", "control_state"):
            if method == "stopped":
                self._perm = {**self._perm, "stopped": bool((params or {}).get("stopped"))}
                self.garvisChanged.emit()
            if method == "activity":
                self._audit = [dict(params or {}, id=None)] + self._audit[:199]
                self.auditChanged.emit()

    @Slot()
    def refreshPermissions(self) -> None:
        if self.engine:
            self.engine.call("admin.permissions.get", {}, lambda r, e: r and self._set("_perm", r, self.garvisChanged))

    @Slot()
    def refreshAudit(self) -> None:
        if self.engine:
            self.engine.call("admin.audit.read", {"limit": 200}, lambda r, e: r and self._set("_audit", r.get("entries", []), self.auditChanged))

    @Slot(str, bool)
    def setScope(self, scope: str, enabled: bool) -> None:
        scopes = list((self._perm.get("clients") or {}).get("garvis") or [])
        if enabled and scope not in scopes:
            scopes.append(scope)
        if not enabled:
            scopes = [s for s in scopes if s != scope]
        self.engine.call("admin.permissions.set", {"client": "garvis", "scopes": scopes},
                         lambda r, e: (self._report(e), self.refreshPermissions()))

    @Slot("QVariantList")
    def setDenyList(self, items) -> None:
        clean = sorted({str(i).strip().lower() for i in items if str(i).strip()})
        self.engine.call("admin.permissions.set", {"deny_list": clean}, lambda r, e: (self._report(e), self.refreshPermissions()))

    @Slot(bool)
    def setStopped(self, stopped: bool) -> None:
        self.engine.call("admin.stop" if stopped else "admin.resume", {}, lambda r, e: (self._report(e), self.refreshPermissions()))

    # ------------------------------------------------------------------ helpers
    def _set(self, attr: str, value, signal) -> None:
        setattr(self, attr, value)
        signal.emit()

    def _report(self, err) -> None:
        if err:
            self.message.emit(err.get("message", "Something went wrong") if isinstance(err, dict) else str(err))

    @Slot(float, result=str)
    def ago(self, t: float) -> str:
        if not t:
            return "never"
        d = time.time() - float(t)
        if d < 60:
            return "just now"
        if d < 3600:
            return f"{int(d // 60)} min ago"
        if d < 86400:
            return f"{int(d // 3600)} h ago"
        return f"{int(d // 86400)} d ago"
