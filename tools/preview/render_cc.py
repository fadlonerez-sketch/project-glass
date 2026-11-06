"""Render every Control Center page (light and dark) to PNG without showing a window.

    .venv\\Scripts\\python tools\\preview\\render_cc.py [--out docs\\preview\\controlcenter]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GLASS_DATA_DIR", tempfile.mkdtemp(prefix="glass-ccpreview-"))

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402

from glass.controlcenter.bridge import ControlCenterBridge  # noqa: E402
from glass.core import paths  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "preview" / "controlcenter"))
    ap.add_argument("--pages", nargs="+", default=["appearance", "glass", "topbar", "dock", "markets", "notifications",
                                                   "applications", "system", "garvis", "about"])
    ap.add_argument("--modes", nargs="+", default=["light", "dark"])
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QGuiApplication(sys.argv)
    bridge = ControlCenterBridge()
    bridge._retheme_local()  # no Shell / engine connections in preview mode
    bridge._apps = [{"app_id": "a", "name": "Google Chrome", "pinned": True, "running": True, "last_launched": 0},
                    {"app_id": "b", "name": "File Explorer", "pinned": True, "running": False, "last_launched": 0},
                    {"app_id": "c", "name": "WhatsApp", "pinned": False, "running": False, "last_launched": 0}]
    bridge._perm = {"clients": {"garvis": ["inspect", "act", "text", "windows"]}, "deny_list": ["keepass.exe", "1password.exe"], "stopped": False}
    bridge._engine_ok = True
    bridge._audit = [{"method": "element.act", "target": "Notepad — Untitled", "client": "garvis", "outcome": "ok", "time": 1793000000},
                     {"method": "element.act", "target": "KeePass", "client": "garvis", "outcome": "denied_app", "time": 1792999000}]
    engine = QQmlApplicationEngine()
    from glass.ui.glyphs import GlyphProvider
    engine.addImageProvider("glyph", GlyphProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("glass", bridge)
    ctx.setContextProperty("cc", bridge)
    ctx.setContextProperty("shaderUrl", QUrl.fromLocalFile(str(paths.SHADER_DIR / "liquidglass.frag.qsb")))
    ctx.setContextProperty("initialPage", "appearance")
    ctx.setContextProperty("previewMode", True)
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(paths.QML_DIR / "controlcenter" / "ControlCenter.qml")))
    win = engine.rootObjects()[0]
    win.setX(-30000)
    win.setY(-30000)
    win.setVisible(True)   # far off-screen: nothing appears on any monitor, but the window gets its real size
    files = []
    for mode in args.modes:
        bridge.set("appearance.theme", mode)
        bridge.set("glass.intensity", 0.7 if mode == "dark" else 0.0)
        pump(300)
        for page in args.pages:
            win.setProperty("page", page)
            pump(900)
            img = win.grabWindow()
            path = out / f"cc-{page}-{mode}.png"
            img.save(str(path))
            files.append(str(path))
    print(json.dumps({"warnings": warnings[:40], "count": len(files)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
