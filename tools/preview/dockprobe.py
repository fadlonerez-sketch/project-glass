"""Measure the real Dock QML off-screen (no input, nothing on any monitor) and print JSON: slot geometry at rest and
while magnified, preview/tooltip placement for every app, the input region in each state, and departure behaviour.
Used by tests/shell/test_dock_qml.py at several display sizes and scale factors.

    python tools\\preview\\dockprobe.py --width 1920 --height 1080 [--scale 1.5] [--position bottom]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--width", type=int, default=1920)
ap.add_argument("--height", type=int, default=1080)
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--position", default="bottom")
args = ap.parse_args()
if args.scale != 1.0:
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402  (sets up an isolated data folder and DPR handling)

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402

from glass.core import paths  # noqa: E402
from glass.core.settings import SettingsStore  # noqa: E402
from glass.shell.controller import GlassController  # noqa: E402
from glass.ui.glyphs import GlyphProvider  # noqa: E402
from glass.win.icons import AppIconProvider  # noqa: E402


def main() -> int:
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    QQuickWindow.setDefaultAlphaBuffer(True)
    app = QGuiApplication(sys.argv)  # noqa: F841 - keep the application alive
    settings = SettingsStore(paths.settings_db())
    settings.patch({"dock.position": args.position,
                    "dock.widgets": [{"id": "weather", "type": "weather"}, {"id": "calendar", "type": "calendar"},
                                     {"id": "garvis", "type": "garvis"}]})
    glass = GlassController(settings)
    dock = render.FakeDock(render.demo_rows(), settings)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("appicon", AppIconProvider(paths.cache_dir() / "icons"))
    engine.addImageProvider("glyph", GlyphProvider())
    ctx = engine.rootContext()
    for k, v in {"glass": glass, "dock": dock, "markets": render.FakeMarkets(), "sysmon": None, "garvisLink": None}.items():
        ctx.setContextProperty(k, v)
    ctx.setContextProperty("shaderUrl", QUrl.fromLocalFile(str(paths.SHADER_DIR / "liquidglass.frag.qsb")))
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    screen = render.FakeScreen(args.width, args.height)
    engine.setInitialProperties({"targetScreen": screen, "isPrimary": True, "screenName": "probe"})
    engine.load(QUrl.fromLocalFile(str(paths.QML_DIR / "Dock.qml")))
    win = engine.rootObjects()[-1]
    win.setX(render.PARK); win.setY(render.PARK)
    render.pump(600)
    hover = dock.hoverState

    def walk(item):
        for c in item.childItems():
            yield c
            yield from walk(c)

    def slots():
        out = {}
        for it in win.contentItem().childItems():
            uid = it.property("uid")
            if isinstance(uid, str) and uid and isinstance(it.property("kind"), str) and it.property("centerWin") is not None:
                vis = it.childItems()[0] if it.childItems() else None
                out[uid] = {"x": it.x(), "y": it.y(), "w": it.width(), "h": it.height(), "center": it.property("centerWin"),
                            "mag": it.property("mag"), "kind": it.property("kind"), "scale": vis.scale() if vis else 1}
        return out

    def region():
        r = win.mask().boundingRect()
        return {"x": r.x(), "y": r.y(), "w": r.width(), "h": r.height(), "rects": win.mask().rectCount()}

    def find(name):
        for it in walk(win.contentItem()):
            if it.metaObject().className().startswith(name):
                return it
        return None

    result = {"window": {"w": win.width(), "h": win.height(), "dpr": win.devicePixelRatio()},
              "bar": {k: win.property(k) for k in ("barX", "barY", "barW", "barH", "barT", "reservedThickness")},
              "rest": slots(), "region_rest": region()}
    apps = [u for u, s in result["rest"].items() if s["kind"] == "app"]

    # magnification: pointer resting on each app in turn; slots must not move
    win.setProperty("magAmount", 1.0)
    mags = {}
    for uid in apps:
        win.setProperty("pointer", result["rest"][uid]["center"])
        render.pump(260)
        mags[uid] = slots()
    result["magnified"] = mags
    win.setProperty("magAmount", 0.0); win.setProperty("pointer", -1)

    # previews and tooltips for every app; placement and region
    preview = find("WindowPreview")
    placements = {}
    for uid in apps:
        running = result["rest"][uid]["kind"] == "app" and uid.split(":", 1)[1] in ("Google Chrome", "File Explorer", "WhatsApp", "Terminal")
        hover.showNow(uid, running)
        render.pump(450)
        t = preview.property("target")
        placements[uid] = {"running": running, "preview_visible": bool(preview.isVisible()), "preview": [t.x(), t.y(), t.width(), t.height()],
                           "margin": preview.property("margin"), "tooltip": win.property("tipText"), "region": region(),
                           "state": hover.state, "shown_preview": hover.preview, "shown_tip": hover.tooltip}
        hover.dismiss()
        render.pump(450)
    result["placements"] = placements
    result["region_after"] = region()

    # departure: an app closes; its slot collapses and the neighbours close the gap
    rows = render.demo_rows()
    gone = "app:WhatsApp"
    dock._model.apply([r for r in rows if r["uid"] != gone], keep_leaving={gone})
    dock.layoutChanged.emit()
    render.pump(500)
    result["leaving"] = slots()
    result["warnings"] = warnings
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
