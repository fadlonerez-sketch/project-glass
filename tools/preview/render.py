"""Render the real Shell QML (top bar, Dynamic Glass states, markets, flyouts, Dock, tooltips, window previews) to
PNG files with demo data, without showing anything on the desktop: windows are parked far off-screen and captured
with QQuickWindow.grabWindow(). Used for design review and as a QML smoke test.

Rendering is deterministic: a virtual 1920x1080 display at device-pixel-ratio 1 regardless of the real monitors.
Live DWM window thumbnails can't appear in an off-screen capture (DWM composites them on screen), so window
previews render with their fallback cards here.

    .venv\\Scripts\\python tools\\preview\\render.py [--out docs\\preview] [--intensity 1] [--modes light dark]
                                                    [--test-backdrop] [--preset crystal]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GLASS_DATA_DIR", tempfile.mkdtemp(prefix="glass-preview-"))
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

from PySide6.QtCore import QEventLoop, QObject, QRect, QTimer, QUrl, Property, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402

from glass.core import material, paths  # noqa: E402
from glass.core.docklayout import compute_layout  # noqa: E402
from glass.core.settings import SettingsStore  # noqa: E402
from glass.shell.controller import GlassController  # noqa: E402
from glass.shell.dock import DockHover, DockModel, icon_url  # noqa: E402
from glass.win.icons import AppIconProvider, BytesImageProvider  # noqa: E402

PARK = -30000
W, H = 1920, 1080


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeScreen(QObject):
    """What the QML reads from targetScreen: its geometry."""
    geometryChanged = Signal()

    def __init__(self, w: int, h: int):
        super().__init__()
        self._g = QRect(0, 0, w, h)

    @Property(QRect, notify=geometryChanged)
    def geometry(self):
        return self._g


class FakeThumbs(QObject):
    @Slot(QObject, "QVariantList", result="QVariantMap")
    def show(self, window, items):
        return {str(int(i["hwnd"])): "unsupported" if int(i["hwnd"]) != 3 else "minimized" for i in items}

    @Slot(QObject)
    def hide(self, window): pass

    @Slot(QObject)
    def clear(self, window): pass


class FakeDock(QObject):
    modelChanged = Signal()
    layoutChanged = Signal()
    foregroundNameChanged = Signal()
    pinnedChanged = Signal()
    keyboardRequested = Signal()
    toast = Signal(str)

    def __init__(self, rows, settings):
        super().__init__()
        self._model = DockModel(self)
        self._model.apply(rows)
        self._hover = DockHover(settings, self)
        self._thumbs = FakeThumbs(self)

    @Property(QObject, notify=modelChanged)
    def model(self):
        return self._model

    @Property(str, notify=foregroundNameChanged)
    def foregroundName(self):
        return "Google Chrome"

    @Property(int, notify=layoutChanged)
    def layoutRevision(self):
        return 1

    @Property(QObject, constant=True)
    def hoverState(self):
        return self._hover

    @Property(QObject, constant=True)
    def thumbnails(self):
        return self._thumbs

    @Slot(float, float, float, bool, result="QVariantMap")
    def layoutFor(self, length, icon, gap, horizontal):
        rows = [{"uid": r["uid"], "kind": r["kind"], "widgetType": r["widgetType"], "section": r["section"], "leaving": bool(r.get("leaving"))}
                for r in self._model.items()]
        return compute_layout(rows, length, icon, gap, horizontal).to_dict()

    @Slot(str, result="QVariantList")
    def windowsFor(self, app_id):
        return self.previewWindows(app_id)

    @Slot(str, result="QVariantList")
    def previewWindows(self, app_id):
        return [{"hwnd": 1, "title": "Project Glass — Design review", "minimized": False, "active": True, "aspect": 1.6},
                {"hwnd": 2, "title": "Inbox (3) — Mail", "minimized": False, "active": False, "aspect": 1.33},
                {"hwnd": 3, "title": "Open-Meteo API docs", "minimized": True, "active": False, "aspect": 1.6}]

    @Slot(str, result=bool)
    def isPinned(self, app_id):
        return True

    @Slot(str)
    def activate(self, a): pass

    @Slot(str)
    def launchApp(self, a): pass

    @Slot(int)
    def focusWindow(self, h): pass

    @Slot(int)
    def minimizeWindow(self, h): pass

    @Slot(int)
    def closeWindow(self, h): pass

    @Slot(str)
    def quitApp(self, a): pass

    @Slot(str)
    def pin(self, a): pass

    @Slot(str)
    def unpin(self, a): pass

    @Slot(str)
    def removeFromDock(self, a): pass

    @Slot("QVariantList")
    def reorderPinned(self, order): pass

    @Slot()
    def returnFocus(self): pass


class FakeMarkets(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        import math
        def spark(seed, up):
            return [100 + (i * (0.08 if up else -0.08)) + math.sin(i / 3 + seed) * 0.9 for i in range(60)]
        def e(sym, label, name, price, chg, up, status="live", lab="Live"):
            return {"symbol": sym, "label": label, "name": name, "price": price, "change": chg,
                    "changePct": chg / (price - chg) * 100, "currency": "USD", "dayHigh": price * 1.01, "dayLow": price * 0.98,
                    "previousClose": price - chg, "spark": spark(len(sym), up), "exchange": "NasdaqGS", "status": status,
                    "statusLabel": lab, "live": status == "live", "error": "", "session": "open"}
        self._d = {"enabled": True, "sparklines": True, "status": "delayed", "label": "Delayed · 15 min",
                   "updated": "Updated 14:32", "source": "Yahoo Finance (unofficial)", "error": "",
                   "indices": [e("^GSPC", "S&P 500", "S&P 500", 7427.81, -60.81, False, "delayed", "Delayed · 15 min"),
                               e("^IXIC", "Nasdaq", "Nasdaq", 25110.4, 182.3, True, "delayed", "Delayed · 15 min"),
                               e("^DJI", "Dow", "Dow", 46902.1, -120.5, False, "delayed", "Delayed · 15 min")],
                   "watchlist": [e("AAPL", "AAPL", "Apple Inc.", 345.14, -4.37, False),
                                 e("MSFT", "MSFT", "Microsoft Corporation", 541.80, -13.99, False),
                                 e("NVDA", "NVDA", "NVIDIA Corporation", 212.55, 3.12, True)]}

    @Property("QVariantMap", notify=changed)
    def data(self):
        return self._d

    @Slot(str)
    def openQuote(self, s): pass


# Fixture networks only. The preview must never scan for (or show) the real Wi-Fi networks around this PC: their
# names are other people's data and would end up in the committed reference images.
DEMO_NETWORK = {"kind": "wifi", "internet": True, "ssid": "Studio 5G", "name": "Studio 5G", "bars": 4, "level": "internet"}
DEMO_WIFI = [{"ssid": "Garden Café", "bars": 3, "secured": False, "connected": False},
             {"ssid": "Neighbor-5G", "bars": 3, "secured": True, "connected": False},
             {"ssid": "Office Guest", "bars": 2, "secured": False, "connected": False},
             {"ssid": "Library Wi-Fi", "bars": 2, "secured": True, "connected": False},
             {"ssid": "Printer-Direct", "bars": 1, "secured": True, "connected": False}]


class FakeNetworkService(QObject):
    """Stands in for glass.win.system.NetworkService: same signals and slots, fixture data, no WinRT calls, so the
    network flyout's automatic scanWifi() never touches the real Wi-Fi adapter."""
    changed = Signal(dict)
    wifiNetworks = Signal(list)
    wifiResult = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = dict(DEMO_NETWORK)

    def start(self) -> None: pass

    def stop(self) -> None: pass

    def refresh(self) -> None:
        self.changed.emit(dict(self.state))

    def scan_wifi(self) -> None:
        self.wifiNetworks.emit([dict(n) for n in DEMO_WIFI])

    def connect_wifi(self, ssid: str, password: str = "") -> None:
        self.wifiResult.emit({"ok": False, "ssid": ssid, "error": "Preview only."})

    def set_wifi_enabled(self, enabled: bool) -> None: pass


def sandbox_network(glass: GlassController) -> FakeNetworkService:
    """Swap the controller's real network service for the fixture one (before any QML can call scanWifi)."""
    real = glass.network_service
    for sig in (real.changed, real.wifiNetworks, real.wifiResult):
        try:
            sig.disconnect()
        except (RuntimeError, TypeError):
            pass
    fake = FakeNetworkService(glass)
    fake.changed.connect(glass._on_network)
    fake.wifiNetworks.connect(glass._on_wifi_networks)
    fake.wifiResult.connect(glass._on_wifi_result)
    glass.network_service = fake
    return fake


def demo_rows() -> list[dict]:
    base = {k: "" for k in ("appId", "name", "section", "icon", "widgetType", "widgetId")}
    base.update(pinned=False, running=False, focused=False, windowCount=0, launching=False, otherDesktop=False, attention=False)
    apps = [
        ("Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe", "open", True, True, 3),
        ("File Explorer", "shell:AppsFolder\\Microsoft.Windows.Explorer", "open", True, False, 1),
        ("WhatsApp", "shell:AppsFolder\\5319275a.WhatsAppDesktop_cv1g1gvanyjgm!App", "open", False, False, 1),
        ("Terminal", "shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App", "open", False, False, 2),
        ("Brave", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe", "recent", True, False, 0),
        ("Settings", "shell:AppsFolder\\windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel", "recent", False, False, 0),
        ("Notepad", "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "recent", False, False, 0),
        ("Task Manager", r"C:\Windows\System32\Taskmgr.exe", "recent", False, False, 0),
    ]
    rows = [{**base, "uid": "launcher", "kind": "launcher", "name": "Search"}]
    for name, src, section, pinned, focused, wins in apps:
        if section == "recent" and rows[-1]["section"] == "open":
            rows.append({**base, "uid": "sep:recent", "kind": "separator"})
        rows.append({**base, "uid": "app:" + name, "kind": "app", "appId": name, "name": name, "section": section,
                     "pinned": pinned, "running": section == "open", "focused": focused, "windowCount": wins,
                     "icon": icon_url(src)})
    rows.append({**base, "uid": "sep:widgets", "kind": "separator"})
    for w in ("weather", "calendar", "system", "garvis"):
        rows.append({**base, "uid": "widget:" + w, "kind": "widget", "widgetType": w, "widgetId": w, "name": w})
    return rows


def demo_data(glass: GlassController) -> None:
    glass._power = {"present": True, "percent": 82, "charging": False, "plugged": False, "saver": False,
                    "remaining_min": 287, "health": 96, "rate_w": -9.8}
    glass._network = dict(DEMO_NETWORK)
    glass._audio = {"available": True, "volume": 0.46, "muted": False, "device": "Speakers (Realtek)"}
    glass._brightness = 72
    glass._media = {"present": True, "playing": True, "title": "Glass Horizons", "artist": "Aurora Keys", "album": "Refraction",
                    "appName": "Spotify", "duration": 214.0, "position": 83.0, "position_updated": time.time(),
                    "can_next": True, "can_prev": True, "can_seek": True, "artworkUrl": "image://artwork/demo"}
    glass._weather = {"enabled": True, "temperature": 21.4, "apparent": 20.1, "condition": "Partly Cloudy", "icon": "partly",
                      "is_day": True, "humidity": 55, "wind": 12.3, "high": 23.0, "low": 14.0, "units": "c", "place": "Lisbon",
                      "hourly": [{"time": f"2026-11-05T{h:02d}:00", "temperature": 21 + (h % 5) * 0.6,
                                  "icon": ["partly", "clear", "clear", "partly", "cloudy", "rain"][i], "is_day": h < 17}
                                 for i, h in enumerate(range(11, 17))],
                      "daily": [{"date": f"2026-11-0{d}", "high": 23 - i, "low": 14 - i * 0.5, "icon": ic, "condition": c}
                                for i, (d, ic, c) in enumerate([(5, "partly", "Partly Cloudy"), (6, "rain", "Rain"),
                                                                (7, "clear", "Clear"), (8, "cloudy", "Overcast"), (9, "thunder", "Thunderstorm")])]}
    glass._garvis = {"engine": True, "active": False, "stopped": False, "app": "Notepad"}
    glass._notifications = [{"app": "Garvis", "title": "Garvis needs your approval", "body": "Send the email to Dana?",
                             "time": time.time() - 120, "source": "garvis"}]
    for sig in (glass.powerChanged, glass.networkChanged, glass.audioChanged, glass.brightnessChanged, glass.mediaChanged,
                glass.weatherChanged, glass.garvisChanged, glass.notificationsChanged):
        sig.emit()


def make_test_backdrop(path: Path, w: int, h: int) -> Path:
    """Saturated stripes, text and shapes: refraction, blur and dispersion are easy to judge on it."""
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QPen
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    for t, c in ((0, "#FF5E62"), (0.25, "#FF9966"), (0.5, "#36D1DC"), (0.75, "#5B86E5"), (1, "#8E5CF7")):
        g.setColorAt(t, QColor(c))
    p.fillRect(img.rect(), g)
    p.setPen(QPen(QColor(255, 255, 255, 150), 6))
    for x in range(0, w, 60):
        p.drawLine(x, 0, x - 400, h)
    p.setPen(QColor(20, 20, 30))
    p.setFont(QFont("Segoe UI", 54, QFont.Weight.Bold))
    for y in range(40, h, 140):
        p.drawText(20, y, "PROJECT GLASS  refraction  blur  dispersion  " * 3)
    p.end()
    img.save(str(path))
    return path


def make_artwork() -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QLinearGradient, QRadialGradient
    img = QImage(300, 300, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 300, 300)
    g.setColorAt(0, QColor("#2B1E5C")); g.setColorAt(0.5, QColor("#8E5CF7")); g.setColorAt(1, QColor("#F2665A"))
    p.fillRect(img.rect(), g)
    r = QRadialGradient(200, 90, 120)
    r.setColorAt(0, QColor(255, 255, 255, 170)); r.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(img.rect(), r)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "preview"))
    ap.add_argument("--modes", nargs="+", default=["light", "dark"])
    ap.add_argument("--intensity", nargs="+", type=float, default=[1.0])
    ap.add_argument("--preset", default="crystal", choices=sorted(material.PRESETS))
    ap.add_argument("--accent", default="")
    ap.add_argument("--only", nargs="*", default=[], help="topbar dock flyouts (default: all)")
    ap.add_argument("--test-backdrop", action="store_true", help="use a colourful synthetic backdrop to judge refraction")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only or ["topbar", "dock", "flyouts"])

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    QQuickWindow.setDefaultAlphaBuffer(True)
    app = QGuiApplication(sys.argv)
    settings = SettingsStore(paths.settings_db())
    settings.patch(dict(material.PRESETS[args.preset]))
    if args.accent:
        settings.patch({"appearance.accent": args.accent})
    settings.patch({"dock.widgets": [{"id": "weather", "type": "weather"}, {"id": "calendar", "type": "calendar"},
                                     {"id": "system", "type": "system"}, {"id": "garvis", "type": "garvis"}]})
    glass = GlassController(settings)
    sandbox_network(glass)
    art = BytesImageProvider()
    art.put("demo", make_artwork())
    glass.artwork = art
    data_dir = Path(os.environ["GLASS_DATA_DIR"])
    if args.test_backdrop:
        bd_path = make_test_backdrop(data_dir / "test-backdrop.png", W, H)
    else:
        from glass.shell.backdrop import BackdropCache
        from glass.shell.app import native_rect
        bd = BackdropCache(paths.cache_dir() / "backdrops")
        bd.refresh()
        src = bd.for_monitor(native_rect(app.primaryScreen()))
        bd_path = data_dir / "backdrop.png"
        QImage(src).scaled(W, H).save(str(bd_path))
    backdrop_img = QImage(str(bd_path)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    screen_name = "preview"
    glass.set_backdrops({screen_name: QUrl.fromLocalFile(str(bd_path)).toString()})
    glass.set_island_screen(screen_name)
    dock = FakeDock(demo_rows(), settings)
    mk = FakeMarkets()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("appicon", AppIconProvider(paths.cache_dir() / "icons"))
    engine.addImageProvider("artwork", art)
    from glass.ui.glyphs import GlyphProvider
    engine.addImageProvider("glyph", GlyphProvider())
    ctx = engine.rootContext()
    for k, v in {"glass": glass, "dock": dock, "markets": mk, "sysmon": None, "garvisLink": None}.items():
        ctx.setContextProperty(k, v)
    ctx.setContextProperty("shaderUrl", QUrl.fromLocalFile(str(paths.SHADER_DIR / "liquidglass.frag.qsb")))
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    fake_screen = FakeScreen(W, H)
    results = {"warnings": warnings, "files": []}

    def load(qml):
        engine.setInitialProperties({"targetScreen": fake_screen, "isPrimary": True, "screenName": screen_name})
        engine.load(QUrl.fromLocalFile(str(paths.QML_DIR / qml)))
        w = engine.rootObjects()[-1]
        w.setX(PARK); w.setY(PARK)
        return w

    top = load("TopBar.qml")
    dockw = load("Dock.qml")
    pump(500)
    demo_data(glass)
    pump(300)

    def grab(win, name, rect: QRect | None = None):
        img = win.grabWindow()
        o = win.property("backdropOrigin")
        under = backdrop_img.copy(int(o.x()), int(o.y()), img.width(), img.height())
        p = QPainter(under)
        p.drawImage(0, 0, img)
        p.end()
        if rect is not None:
            under = under.copy(rect)
        path = out / f"{name}.png"
        under.save(str(path))
        try:
            results["files"].append(str(path.resolve().relative_to(ROOT)))   # no user profile path in the report
        except ValueError:
            results["files"].append(path.name)

    def set_state(state, payload=None):
        glass._state = state
        glass._payload = payload or {}
        glass.stateChanged.emit()
        pump(1300)

    hover = dock.hoverState
    for mode in args.modes:
        settings.patch({"appearance.theme": mode})
        for inten in args.intensity:
            settings.patch({"glass.intensity": inten})
            pump(900)
            tag = f"{mode}-i{int(inten * 100)}"
            centre = QRect(W // 2 - 560, 0, 1120, 260)
            if "topbar" in only:
                set_state("idle"); grab(top, f"topbar-{tag}", QRect(0, 0, W, 90))
                grab(top, f"pill-idle-{tag}", centre)
                set_state("media", {"playing": True}); grab(top, f"pill-media-{tag}", centre)
                set_state("media_expanded"); grab(top, f"pill-media-expanded-{tag}", centre)
                set_state("notification", {"title": "Garvis needs your approval", "body": "Send the email to Dana about Thursday?",
                                            "source": "garvis", "app": "Garvis"})
                grab(top, f"pill-notification-{tag}", centre)
                set_state("activity", {"kind": "volume", "level": 0.46}); grab(top, f"pill-activity-volume-{tag}", centre)
                set_state("garvis"); grab(top, f"pill-garvis-{tag}", centre)
                set_state("control_center"); grab(top, f"pill-control-center-{tag}", QRect(W // 2 - 330, 0, 660, 720))
                set_state("idle")
            if "flyouts" in only:
                for fly in ("network", "battery", "audio", "clock", "glass", "power"):
                    top.setProperty("flyoutX", W - 120 if fly != "glass" else 14)
                    top.setProperty("flyout", fly)
                    pump(700)
                    grab(top, f"flyout-{fly}-{tag}", QRect(W - 460, 0, 460, 620) if fly != "glass" else QRect(0, 0, 460, 460))
                    top.setProperty("flyout", "")
                    pump(250)
            if "dock" in only:
                dh = dockw.height()
                strip = QRect(0, dh - 330, W, 330)
                hover.dismiss(); pump(400)
                grab(dockw, f"dock-{tag}", QRect(0, dh - 110, W, 110))
                # magnified around Chrome, as if the pointer rested on it
                lay = dockw.property("lay")
                slot = lay["slots"]["app:Google Chrome"]
                cx = dockw.property("barX") + dockw.property("hpad") + slot["center"]
                dockw.setProperty("pointer", cx)
                dockw.setProperty("magAmount", 1.0)
                pump(500)
                grab(dockw, f"dock-magnified-{tag}", QRect(int(cx) - 360, dh - 150, 720, 150))
                hover.showNow("app:Notepad", False); pump(500)
                grab(dockw, f"dock-tooltip-{tag}", strip)
                hover.showNow("app:Google Chrome", True); pump(900)
                grab(dockw, f"dock-preview-{tag}", strip)
                hover.dismiss(); dockw.setProperty("magAmount", 0.0); dockw.setProperty("pointer", -1); pump(500)
    Path(out / "render-report.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"warnings": warnings[:40], "count": len(results["files"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
