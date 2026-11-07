"""python -m glass.controlcenter [--page appearance|glass|topbar|dock|markets|notifications|applications|system|garvis|about]"""
from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

from glass.controlcenter.bridge import ControlCenterBridge
from glass.core import paths, security

AUMID = "ProjectGlass.ControlCenter"
PAGES = ("appearance", "glass", "topbar", "dock", "markets", "notifications", "applications", "system", "garvis", "about")


def _style_titlebar(win, dark: bool, caption: str) -> None:
    """Native caption that matches the content: dark mode flag + caption colour (Windows 11)."""
    try:
        hwnd = int(win.winId())
        dwm = ctypes.windll.dwmapi
        v = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), 4)
        c = caption.lstrip("#")
        colorref = ctypes.c_int(int(c[4:6] + c[2:4] + c[0:2], 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), 4)
        corner = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), 4)
        from glass.shell.extras import mark_protected
        mark_protected(hwnd)
    except Exception:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="glass.controlcenter")
    ap.add_argument("--page", default="", choices=("",) + PAGES)
    args = ap.parse_args(argv)
    handler = logging.handlers.RotatingFileHandler(paths.logs_dir() / "controlcenter.log", maxBytes=500_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except OSError:
        pass
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Glass Control Center")
    app.setFont(QFont("Segoe UI Variable Text", 10))

    # Single instance: a second launch just brings the window forward (optionally on a page).
    name = security.pipe_name("ControlCenter")
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(300):
        probe.write((args.page or "show").encode())
        probe.waitForBytesWritten(500)
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(name)
    server.listen(name)

    bridge = ControlCenterBridge()
    engine = QQmlApplicationEngine()
    from glass.ui.glyphs import GlyphProvider
    engine.addImageProvider("glyph", GlyphProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("glass", bridge)
    ctx.setContextProperty("cc", bridge)
    ctx.setContextProperty("shaderUrl", QUrl.fromLocalFile(str(paths.SHADER_DIR / "liquidglass.frag.qsb")))
    ctx.setContextProperty("initialPage", args.page or "appearance")
    ctx.setContextProperty("previewMode", False)
    hints = app.styleHints()
    bridge.start(hints.colorScheme() == Qt.ColorScheme.Dark)
    hints.colorSchemeChanged.connect(lambda s: bridge.set_system_dark(s == Qt.ColorScheme.Dark))
    engine.load(QUrl.fromLocalFile(str(paths.QML_DIR / "controlcenter" / "ControlCenter.qml")))
    if not engine.rootObjects():
        return 1
    win = engine.rootObjects()[0]

    def restyle():
        _style_titlebar(win, bool(bridge.theme.get("dark")), bridge.theme.get("bg", "#F3F3F6"))
    bridge.themeChanged.connect(restyle)
    QTimer.singleShot(0, restyle)

    def on_conn():
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()

            def read(s=sock):
                page = bytes(s.readAll()).decode("utf-8", "replace").strip()
                if page in PAGES:
                    bridge.pageRequested.emit(page)
                win.show()
                win.raise_()
                win.requestActivate()
            sock.readyRead.connect(read)
    server.newConnection.connect(on_conn)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
