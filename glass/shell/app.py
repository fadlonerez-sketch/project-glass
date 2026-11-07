"""Glass.Shell bootstrap: services, windows per display, space reservation, taskbar, engine, watchdog, and the
master power switch (Glass on: surfaces shown, space reserved, taskbar replaced; off: Windows exactly as normal,
with the Shell resident so it can be switched back on, and recovery still armed)."""
from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QGuiApplication, QFont, QScreen
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

from glass import __version__
from glass.core import paths, security
from glass.core.apps import AppRegistry
from glass.core.ipc import ErrorCode, ProtocolError
from glass.core.settings import SettingsStore
from glass.core.weather import WeatherError
from glass.shell.backdrop import BackdropCache
from glass.shell.controller import GlassController
from glass.shell.dock import DockController
from glass.shell.extras import GarvisLink, SysMon, mark_protected
from glass.shell.markets import MarketsService
from glass.shell.server import ShellServer
from glass.win import appwin, shellbar
from glass.win.icons import AppIconProvider, BytesImageProvider
from glass.win.tracker import WindowTracker

log = logging.getLogger("glass.shell")

WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012
SPI_SETDESKWALLPAPER = 0x0014
SHELL_AUMID = "ProjectGlass.Shell"
EMERGENCY_HOTKEY = "Ctrl+Alt+Shift+Q"
POWER_HOTKEY = "Ctrl+Alt+Shift+G"
DOCK_KEYBOARD_HOTKEY = "Ctrl+Alt+Shift+D"


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def monitor_rects() -> dict[str, tuple[int, int, int, int]]:
    """Physical monitor rectangles by device name (\\\\.\\DISPLAY1), as AppBars need them."""
    user32 = ctypes.windll.user32
    out: dict[str, tuple[int, int, int, int]] = {}
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rc, lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            out[mi.szDevice] = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        return True

    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return out


def native_rect(screen: QScreen) -> tuple[int, int, int, int]:
    """A screen's physical rectangle. Qt keeps each screen's native origin and a DPI-scaled size."""
    g, dpr = screen.geometry(), screen.devicePixelRatio()
    return (g.x(), g.y(), int(round(g.width() * dpr)), int(round(g.height() * dpr)))


def setup_logging(level: str = "INFO") -> None:
    handler = logging.handlers.RotatingFileHandler(paths.logs_dir() / "shell.log", maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def python_exe(windowed: bool = True) -> str:
    exe = Path(sys.executable)
    if windowed and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        return str(exe.parent / "pythonw.exe")
    return str(exe)


class NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, shell: "ShellApp"):
        super().__init__()
        self.shell = shell

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG" and event_type != "windows_generic_MSG":
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        m = msg.message
        if m == shellbar.WM_HOTKEY:
            return self.shell.hotkeys.handle(m, msg.wParam), 0
        if m == shellbar.APPBAR_CALLBACK:
            self.shell.on_appbar(int(msg.hWnd or 0), int(msg.wParam), int(msg.lParam))
        elif m == shellbar.TASKBAR_CREATED:
            QTimer.singleShot(1500, self.shell.on_explorer_restarted)
        elif m == WM_SETTINGCHANGE:
            if msg.wParam == SPI_SETDESKWALLPAPER:
                self.shell.schedule_backdrop()
        elif m == WM_DISPLAYCHANGE:
            self.shell.schedule_layout()
        elif m == WM_POWERBROADCAST and msg.wParam == PBT_APMRESUMEAUTOMATIC:
            QTimer.singleShot(2500, self.shell.on_resume)
        return False, 0


class ShellApp(QObject):
    quitting = Signal()

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.app = QGuiApplication.instance()
        self.settings = SettingsStore(paths.settings_db())
        self.registry = AppRegistry(paths.apps_db())
        self.catalog = appwin.AppCatalog()
        self.tracker = WindowTracker(self)
        self.glass = GlassController(self.settings, self)
        self.dock = DockController(self.settings, self.registry, self.catalog, self.tracker, self)
        self.backdrops = BackdropCache(paths.cache_dir() / "backdrops")
        self.taskbar = shellbar.TaskbarController(paths.state_file())
        self.hotkeys = shellbar.GlobalHotkeys()
        self.engine_proc: subprocess.Popen | None = None
        self.engine_client = None
        self.watchdog: subprocess.Popen | None = None
        self.windows: dict[str, dict] = {}     # screen name -> {"top": QQuickWindow, "dock": QQuickWindow, "bars": [...]}
        self.appbars: dict[int, shellbar.AppBar] = {}
        self.fullscreen: set[int] = set()
        self._layout_timer = QTimer(self, singleShot=True, interval=600)
        self._layout_timer.timeout.connect(self.rebuild_windows)
        self._backdrop_timer = QTimer(self, singleShot=True, interval=800)
        self._backdrop_timer.timeout.connect(self.refresh_backdrops)
        self._engine_restarts: list[float] = []
        self.qml = QQmlApplicationEngine(self)
        self.icon_provider = AppIconProvider(paths.cache_dir() / "icons")
        self.artwork = BytesImageProvider()
        self.glass.artwork = self.artwork
        self.qml.addImageProvider("appicon", self.icon_provider)
        self.qml.addImageProvider("artwork", self.artwork)
        from glass.ui.glyphs import GlyphProvider
        self.qml.addImageProvider("glyph", GlyphProvider())
        ctx = self.qml.rootContext()
        ctx.setContextProperty("glass", self.glass)
        ctx.setContextProperty("dock", self.dock)
        self.sysmon = SysMon(self)
        self.garvis_link = GarvisLink(parent=self)
        self.markets = MarketsService(self.settings, parent=self)
        ctx.setContextProperty("markets", self.markets)
        ctx.setContextProperty("sysmon", self.sysmon)
        ctx.setContextProperty("garvisLink", self.garvis_link)
        self.garvis_link.failed.connect(lambda m: self.glass.notify({"app": "Glass", "title": m, "source": "glass"}))
        self.glass.toast.connect(lambda m: self.glass.notify({"app": "Glass", "title": m, "source": "glass"}))
        self.dock.toast.connect(lambda m: self.glass.notify({"app": "Glass", "title": m, "source": "glass"}))
        ctx.setContextProperty("shaderUrl", QUrl.fromLocalFile(str(paths.SHADER_DIR / "liquidglass.frag.qsb")))
        self.qml.addImportPath(str(paths.QML_DIR))
        self.qml.warnings.connect(lambda ws: [log.warning("QML: %s", w.toString()) for w in ws])
        self.server = ShellServer(self._api_handlers(), self._api_async_handlers(), parent=self)
        self.glass.requestControlCenter.connect(self.open_control_center)
        self.glass.requestRestore.connect(self.restore_windows_desktop)
        self.glass.requestQuit.connect(self.quit)
        self.glass.requestRevealTray.connect(lambda: self.taskbar.reveal(12.0))
        self.glass.requestPower.connect(lambda on: self.settings.patch({"system.enabled": bool(on)}))
        self.glass.poweredChanged.connect(lambda: self.server.broadcast(
            "power.changed", {"powered": self.glass.powered, "busy": self.glass.powerBusy}))
        self.powered = False
        self.glass.emergency_stop_handler = lambda: self._engine_call("admin.stop")
        self.glass.resume_handler = lambda: self._engine_call("admin.resume")
        self.glass.app_name_lookup = self._name_for_aumid
        self.tracker.foregroundChanged.connect(self._on_foreground)
        self.settings.subscribe(lambda ch: QTimer.singleShot(0, lambda: self._on_settings(ch)))

    # ------------------------------------------------------------------ startup
    def start(self) -> None:
        log.info("Project Glass %s starting (pid %d)", __version__, os.getpid())
        self._write_state(clean_exit=False, shell_pid=os.getpid(), started=time.time())
        if not self.args.no_watchdog:
            self.start_watchdog()
        if security.read_secret("owner") is None:
            # Normally the engine issues the owner token; without it (--no-engine) the Shell API still needs one.
            security.write_secret("owner", security.new_token())
        self.server.listen()
        if not self.args.no_engine:
            self.start_engine()
        hints = self.app.styleHints()
        hints.colorSchemeChanged.connect(lambda scheme: self.glass.set_system_dark(scheme == Qt.ColorScheme.Dark))
        self.glass.set_system_dark(hints.colorScheme() == Qt.ColorScheme.Dark)
        self.refresh_backdrops()
        self.glass.start()
        self.catalog.load()
        self.dock.seed_default_pins()
        self.dock.seed_from_launchdeck()
        if self.settings.get("system.enabled"):
            self.power_on()
        else:
            log.info("Glass is switched off; staying resident until it is switched on")
            self.glass.set_powered(False)
            self._write_state(powered=False)
        if not self.args.test_mode:
            self.hotkeys.register(EMERGENCY_HOTKEY, self.glass.emergencyStop)
            self.hotkeys.register(POWER_HOTKEY, lambda: self.settings.patch({"system.enabled": not self.powered}))
            self.hotkeys.register(DOCK_KEYBOARD_HOTKEY, lambda: self.powered and self.dock.requestKeyboard())
        self.app.screenAdded.connect(lambda *_: self.schedule_layout())
        self.app.screenRemoved.connect(lambda *_: self.schedule_layout())
        self.app.primaryScreenChanged.connect(lambda *_: self.schedule_layout())
        self.app.aboutToQuit.connect(self._shutdown)
        log.info("Project Glass started")

    # ------------------------------------------------------------------ the master power switch
    def power_on(self) -> None:
        """Bring the whole configured experience up. The UI switch reflects this only once it has happened."""
        if self.powered:
            return
        log.info("Glass: on")
        self.glass.set_powered(False, busy=True)
        self.tracker.start()
        self.glass.resume_services()
        self.markets.start()
        self.rebuild_windows()
        if self.settings.get("system.hide_taskbar") and not self.args.keep_taskbar and not self.args.test_mode:
            self.taskbar.hide()
        self.powered = True
        self._write_state(powered=True)
        self.glass.set_powered(True)

    def power_off(self) -> None:
        """Windows exactly as normal: every Glass surface closed, reserved space released, the taskbar restored and
        Glass's background work paused. Settings are untouched; the recovery watchdog and hotkeys stay armed, and the
        computer-control engine keeps serving Garvis (it is not part of the visual shell)."""
        if not self.powered:
            return
        log.info("Glass: off")
        self.glass.set_powered(True, busy=True)
        self.glass.closeAll()
        self.dock.thumbs.clear_all()
        self._close_windows()
        self.taskbar.restore()
        self.tracker.stop()
        self.markets.stop()
        self.sysmon.set_active(False)
        self.glass.pause_services()
        self.powered = False
        self._write_state(powered=False)
        self.glass.set_powered(False)

    def _close_windows(self) -> None:
        for ab in self.appbars.values():
            ab.unregister()
        self.appbars.clear()
        for entry in self.windows.values():
            for w in entry.values():
                w.close()
                w.deleteLater()
        self.windows.clear()

    def _write_state(self, **changes) -> None:
        st = shellbar.read_state(paths.state_file())
        st.update(changes)
        shellbar.write_state(paths.state_file(), st)

    # ------------------------------------------------------------------ watchdog / engine
    def start_watchdog(self) -> None:
        cmd = [python_exe(), "-m", "glass.recovery", "--watch", str(os.getpid())]
        try:
            self.watchdog = subprocess.Popen(cmd, cwd=str(paths.PROJECT_DIR), creationflags=subprocess.DETACHED_PROCESS
                                             | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
            log.info("watchdog started (pid %d)", self.watchdog.pid)
        except OSError as exc:
            log.error("watchdog could not start: %s", exc)

    def start_engine(self) -> None:
        cmd = [python_exe(), "-m", "glass.automation", "--parent-pid", str(os.getpid())]
        try:
            self.engine_proc = subprocess.Popen(cmd, cwd=str(paths.PROJECT_DIR), creationflags=subprocess.CREATE_NO_WINDOW)
            log.info("automation engine started (pid %d)", self.engine_proc.pid)
        except OSError as exc:
            log.error("automation engine could not start: %s", exc)
            return
        if self.engine_client is None:
            try:
                from glass.automation.qtclient import EngineClient
            except Exception as exc:  # engine package missing/broken: the Shell still runs
                log.error("engine client unavailable: %s", exc)
                return
            self.engine_client = EngineClient(client_name="owner", subscribe_admin=True, parent=self)
            self.engine_client.connectedChanged.connect(self._on_engine_connected)
            self.engine_client.notification.connect(self._on_engine_event)
            QTimer.singleShot(400, self.engine_client.start)
            self._engine_watch = QTimer(self, interval=5000)
            self._engine_watch.timeout.connect(self._check_engine)
            self._engine_watch.start()

    def _check_engine(self) -> None:
        if self.engine_proc is not None and self.engine_proc.poll() is not None and not self.args.no_engine:
            now = time.time()
            self._engine_restarts = [t for t in self._engine_restarts if now - t < 300] + [now]
            if len(self._engine_restarts) > 3:
                log.error("automation engine keeps exiting; not restarting again")
                self.glass.set_garvis(engine=False, error="The computer-control engine stopped repeatedly.")
                self._engine_watch.stop()
                return
            log.warning("automation engine exited (%s); restarting", self.engine_proc.returncode)
            self.start_engine()

    def _on_engine_connected(self, ok: bool) -> None:
        self.glass.set_garvis(engine=bool(ok))
        if ok:
            self._engine_call("engine.status", callback=lambda r, e: r and self.glass.set_garvis(stopped=bool(r.get("stopped"))))

    def _on_engine_event(self, method: str, params) -> None:
        params = params or {}
        if method == "control_state":
            self.glass.set_garvis(active=bool(params.get("active")), app=params.get("app", ""),
                                  title=params.get("title", ""), client=params.get("client", ""))
        elif method == "stopped":
            self.glass.set_garvis(stopped=bool(params.get("stopped")))
        elif method == "notification":
            if self.settings.get("notifications.garvis"):
                self.glass.notify({"app": params.get("app") or "Garvis", "title": params.get("title", ""),
                                   "body": params.get("body", ""), "kind": params.get("kind", "info"),
                                   "source": "garvis"},
                                  priority="high" if params.get("kind") == "confirmation" else "normal")

    def _engine_call(self, method: str, params: dict | None = None, callback=None) -> None:
        if self.engine_client is not None:
            self.engine_client.call(method, params or {}, callback)

    # ------------------------------------------------------------------ windows
    def schedule_layout(self) -> None:
        if self.powered:
            self._layout_timer.start()

    def schedule_backdrop(self) -> None:
        self._backdrop_timer.start()

    def refresh_backdrops(self) -> None:
        try:
            mapping = self.backdrops.refresh()
        except Exception:
            log.exception("backdrop refresh failed")
            return
        by_name = {}
        for screen in self.app.screens():
            path = self.backdrops.for_monitor(native_rect(screen)) if mapping else ""
            by_name[screen.name()] = QUrl.fromLocalFile(path).toString() if path else ""
        self.glass.set_backdrops(by_name)

    def _screens_for(self, kind: str) -> list[QScreen]:
        primary = self.app.primaryScreen()
        if kind == "top" and self.settings.get("topbar.displays") == "all":
            return list(self.app.screens())
        return [primary] if primary else []

    def rebuild_windows(self) -> None:
        self._close_windows()
        if not self.settings.get("system.enabled"):
            return
        primary = self.app.primaryScreen()
        for screen in self.app.screens():
            entry: dict = {}
            if self.settings.get("topbar.visible") and screen in self._screens_for("top"):
                entry["top"] = self._create("TopBar.qml", screen, primary=screen is primary)
            if self.settings.get("dock.visible") and screen in self._screens_for("dock"):
                entry["dock"] = self._create("Dock.qml", screen, primary=True)
            if entry:
                self.windows[screen.name()] = entry
        QTimer.singleShot(300, self.reserve_space)
        self.sysmon.set_active(any(w.get("type") == "system" for w in self.settings.get("dock.widgets")))
        self.update_island()

    def _create(self, qml: str, screen: QScreen, primary: bool) -> QQuickWindow:
        comp_url = QUrl.fromLocalFile(str(paths.QML_DIR / qml))
        self.qml.setInitialProperties({"targetScreen": screen, "isPrimary": primary, "screenName": screen.name()})
        self.qml.load(comp_url)
        objs = self.qml.rootObjects()
        win = objs[-1] if objs else None
        if win is None:
            raise RuntimeError(f"{qml} failed to load")
        win.setScreen(screen)
        if self.args.test_mode:
            win.setX(-30000)   # automated tests: real windows, real rendering, nothing on any monitor
            win.setY(-30000)
        mark_protected(int(win.winId()))
        return win

    def reserve_space(self) -> None:
        if not self.settings.get("system.reserve_space") or self.args.test_mode:
            return
        screens = {s.name(): s for s in self.app.screens()}
        for name, entry in self.windows.items():
            if name not in screens:
                continue
            rect = native_rect(screens[name])
            for kind, win in entry.items():
                hwnd = int(win.winId())
                thickness_logical = win.property("reservedThickness") or 0
                if not thickness_logical:
                    continue
                if kind == "dock" and self.settings.get("dock.autohide"):
                    continue
                edge = shellbar.ABE_TOP if kind == "top" else {
                    "bottom": shellbar.ABE_BOTTOM, "left": shellbar.ABE_LEFT, "right": shellbar.ABE_RIGHT
                }[self.settings.get("dock.position")]
                ab = shellbar.AppBar(hwnd, edge)
                if ab.register():
                    dpr = win.screen().devicePixelRatio() if win.screen() else 1.0
                    ab.set_position(rect, int(round(float(thickness_logical) * dpr)))
                    self.appbars[hwnd] = ab

    def on_appbar(self, hwnd: int, code: int, lparam: int) -> None:
        ab = self.appbars.get(hwnd)
        if ab is None:
            return
        if code == shellbar.ABN_POSCHANGED:
            ab.reapply()
        elif code == shellbar.ABN_FULLSCREENAPP:
            # A full-screen app (video, game, presentation) owns the display: step aside until it ends.
            # Windows tells each app bar about full-screen apps on its own monitor.
            entering = bool(lparam)
            for entry in self.windows.values():
                if any(int(w.winId()) == hwnd for w in entry.values()):
                    for win in entry.values():
                        win.setProperty("suspended", entering)
            log.info("full-screen app %s", "started" if entering else "ended")

    def on_explorer_restarted(self) -> None:
        log.info("Explorer restarted; re-applying taskbar and app bars")
        self.taskbar.explorer_restarted()
        for ab in self.appbars.values():
            ab.registered = False
            ab.register()
            ab.reapply()

    def on_resume(self) -> None:
        log.info("resumed from sleep")
        self.glass.refreshWeather()
        self.glass.power_service.refresh()
        self.glass.network_service.refresh()
        self.tracker.request_rescan()
        self.schedule_layout()

    def update_island(self, hwnd: int = 0) -> None:
        """Host the Dynamic Glass on the display of the frontmost app (when it has a top bar), else the primary."""
        from glass.core.states import pick_island_screen
        tops = [name for name, e in self.windows.items() if "top" in e]
        primary = self.app.primaryScreen()
        mode = self.settings.get("topbar.island_display")
        fg_screen = ""
        if mode == "active" and len(tops) > 1:
            hwnd = hwnd or int(ctypes.windll.user32.GetForegroundWindow() or 0)
            if hwnd and appwin.class_name(hwnd) not in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                fg_screen = self._screen_of_window(hwnd)
        self.glass.set_island_screen(pick_island_screen(tops, primary.name() if primary else "", mode, fg_screen,
                                                        self.glass.islandScreen))

    def _screen_of_window(self, hwnd: int) -> str:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        hmon = user32.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return ""
        r = mi.rcMonitor
        rect = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        for screen in self.app.screens():
            if native_rect(screen) == rect:
                return screen.name()
        return ""

    def _on_foreground(self, hwnd: int) -> None:
        own = {int(w.winId()) for e in self.windows.values() for w in e.values()}
        if hwnd and hwnd not in own:
            self.update_island(hwnd)
            self.glass.closeAll()
            if self.taskbar.hidden:
                tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
                if hwnd != tray:
                    self.taskbar.end_reveal()

    def _on_settings(self, changed: dict) -> None:
        relayout = {"topbar.visible", "topbar.displays", "topbar.size", "dock.visible", "dock.position",
                    "dock.icon_size", "dock.autohide", "system.reserve_space"}
        if "system.enabled" in changed:
            (self.power_on if changed["system.enabled"] else self.power_off)()
        elif relayout & set(changed) and self.powered:
            self.schedule_layout()
        if "topbar.island_display" in changed:
            self.update_island()
        if "system.hide_taskbar" in changed and not self.args.test_mode and self.powered:
            (self.taskbar.hide if changed["system.hide_taskbar"] else self.taskbar.restore)()
        if "system.start_with_windows" in changed:
            from glass.win import startup
            startup.set_enabled(bool(changed["system.start_with_windows"]))
        if "dock.widgets" in changed and self.powered:
            self.sysmon.set_active(any(w.get("type") == "system" for w in changed["dock.widgets"]))
        if "dock.all_desktops" in changed:
            self.dock.refresh()
        if any(k.startswith(("appearance.", "glass.")) for k in changed):
            self.server.broadcast("theme.changed", {"theme": self.glass.theme, "material": self.glass.material})
        self.server.broadcast("settings.changed", {"changed": changed})

    def _name_for_aumid(self, aumid: str) -> str:
        from glass.core.apps import aumid_key
        e = self.catalog.lookup([aumid_key(aumid)])
        return e.name if e else ""

    # ------------------------------------------------------------------ Control Center & recovery
    def open_control_center(self, page: str = "") -> None:
        cmd = [python_exe(), "-m", "glass.controlcenter"] + (["--page", page] if page else [])
        subprocess.Popen(cmd, cwd=str(paths.PROJECT_DIR), creationflags=subprocess.CREATE_NO_WINDOW)

    def restore_windows_desktop(self) -> None:
        log.info("Restore Windows Desktop requested")
        self.quit()

    def quit(self) -> None:
        self.app.quit()

    def _shutdown(self) -> None:
        log.info("shutting down")
        self.hotkeys.unregister_all()
        self.tracker.stop()
        self.markets.stop()
        self.dock.thumbs.clear_all()
        for ab in self.appbars.values():
            ab.unregister()
        self.taskbar.restore()
        self.server.close()
        if self.engine_proc and self.engine_proc.poll() is None:
            self.engine_proc.terminate()
        self._write_state(clean_exit=True, stopped=time.time())
        # Tear the QML down while the objects it binds to still exist (no binding errors at exit).
        import shiboken6
        for entry in self.windows.values():
            for w in entry.values():
                w.close()
        self.windows.clear()
        if shiboken6.isValid(self.qml):
            shiboken6.delete(self.qml)

    # ------------------------------------------------------------------ Shell API (Control Center)
    def _api_handlers(self) -> dict:
        def settings_patch(p):
            res = self.settings.patch(dict(p.get("values") or {}))
            return {"changed": res.changed, "errors": res.errors}

        def settings_reset(p):
            res = self.settings.reset(keys=p.get("keys"), section=p.get("section"))
            return {"changed": res.changed}

        def dock_op(p):
            op, app_id = p.get("op"), p.get("app_id", "")
            if op == "pin":
                self.dock.pin(app_id)
            elif op == "unpin":
                self.dock.unpin(app_id)
            elif op == "remove":
                self.dock.removeFromDock(app_id)
            elif op == "move":
                self.dock.movePinned(app_id, int(p.get("index", 0)))
            elif op == "add":
                return self.dock.add_from_catalog(p.get("parsing", ""))
            else:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown dock op {op}")
            return {"ok": True}

        def catalog_search(p):
            return [{"name": e.name, "parsing": e.parsing, "icon": e.launch} for e in self.catalog.search(p.get("text", ""), 60)]

        def status(_):
            return {"power": self.glass.power, "network": self.glass.network, "audio": self.glass.audio,
                    "brightness": self.glass.brightness, "garvis": self.glass.garvis,
                    "mirror": self.glass.mirrorStatus, "taskbar_hidden": self.taskbar.hidden,
                    "appbars": len(self.appbars), "version": __version__, "powered": self.powered,
                    "island": self.glass.islandScreen, "windows": sorted(f"{n}:{k}" for n, e in self.windows.items() for k in e),
                    "hwnds": {f"{n}:{k}": int(w.winId()) for n, e in self.windows.items() for k, w in e.items()},
                    "screens": [s.name() for s in self.app.screens()]}

        def shell_cmd(p):
            cmd = p.get("command")
            actions = {"restore_taskbar": self.taskbar.restore, "hide_taskbar": self.taskbar.hide,
                       "reveal_tray": lambda: self.taskbar.reveal(12.0), "quit": lambda: QTimer.singleShot(200, self.quit),
                       "refresh_weather": self.glass.refreshWeather, "rescan": self.tracker.request_rescan,
                       "power_on": lambda: self.settings.patch({"system.enabled": True}),
                       "power_off": lambda: self.settings.patch({"system.enabled": False}),
                       "refresh_markets": self.markets.refresh}
            if cmd not in actions:
                raise ProtocolError(ErrorCode.INVALID_PARAMS, f"unknown command {cmd}")
            actions[cmd]()
            return {"ok": True}

        return {
            "settings.get": lambda p: {"values": self.settings.all()},
            "settings.patch": settings_patch,
            "settings.reset": settings_reset,
            "theme.get": lambda p: {"theme": self.glass.theme, "material": self.glass.material},
            "dock.apps": lambda p: {"apps": self.dock.dock_apps()},
            "dock.op": dock_op,
            "catalog.search": catalog_search,
            "status.get": status,
            "notifications.list": lambda p: {"items": self.glass.notifications, "mirror": self.glass.mirrorStatus},
            "shell.command": shell_cmd,
            "markets.get": lambda p: self.markets.data,
        }

    def _api_async_handlers(self) -> dict:
        def weather_search(p):
            try:
                places = self.glass.weather_client.search(str(p.get("query", "")))
            except WeatherError as exc:
                raise ProtocolError(ErrorCode.INTERNAL, str(exc)) from exc
            return {"places": [{"name": pl.name, "label": pl.label, "latitude": pl.latitude, "longitude": pl.longitude}
                               for pl in places]}
        def markets_search(p):
            from glass.core.markets import MarketError
            try:
                return {"results": self.markets.client.search(str(p.get("query", "")))}
            except MarketError as exc:
                raise ProtocolError(ErrorCode.INTERNAL, str(exc)) from exc
        return {"weather.search": weather_search, "markets.search": markets_search}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="glass.shell")
    ap.add_argument("--keep-taskbar", action="store_true", help="don't hide the Windows taskbar this session")
    ap.add_argument("--no-engine", action="store_true", help="don't start the computer-control engine")
    ap.add_argument("--no-watchdog", action="store_true", help="don't start the recovery watchdog (development)")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--test-mode", action="store_true",
                    help="automated tests: windows off-screen, no space reservation, taskbar or hotkeys")
    return ap.parse_args(argv)


def already_running() -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(security.pipe_name("Shell"))
    ok = s.waitForConnected(300)
    s.abort()
    return ok


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(SHELL_AUMID)
    except OSError:
        pass
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    QQuickWindow.setDefaultAlphaBuffer(True)
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Project Glass")
    app.setFont(QFont("Segoe UI Variable Text", 10))
    if already_running():
        log.info("Glass is already running; asking it to switch on")
        try:
            from glass.core.pipeclient import PipeClient
            with PipeClient("Shell", timeout=3) as c:
                c.call("shell.command", {"command": "power_on"})
        except Exception as exc:
            log.warning("could not reach the running Glass: %s", exc)
        return 0
    shell = ShellApp(args)
    filt = NativeFilter(shell)
    app.installNativeEventFilter(filt)
    shell.start()
    return app.exec()
