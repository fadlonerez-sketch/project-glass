"""Project Glass rendering performance test (Qt Quick + Liquid Glass shader).

Shows two non-activating, click-through overlay windows for a few seconds -- a Dynamic Glass pill that
expands/collapses continuously and a dock whose icons ripple -- with the glass material at full
intensity and then at 0 (base material). Reports frame pacing (frameSwapped intervals), process CPU
time, and the cost of a GDI region capture (the candidate "live backdrop" source).

    .venv\\Scripts\\python tools\\perf\\render_perf.py [--seconds 5] [--api d3d11|d3d12|opengl]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import statistics
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

ROOT = Path(__file__).resolve().parents[2]
SHADER = ROOT / "glass" / "ui" / "shaders" / "liquidglass.frag.qsb"

QML = r"""
import QtQuick
import QtQuick.Window

QtObject {
    id: root
    property real intensity: 1.0
    property url wallpaper
    property size wallSize: Qt.size(2560, 1600)

    function backdropRect(win, item) {
        // Wallpaper drawn in "Fill" mode across the primary screen.
        var sw = Screen.width, sh = Screen.height
        var s = Math.max(sw / wallSize.width, sh / wallSize.height)
        var dw = wallSize.width * s, dh = wallSize.height * s
        var ox = (sw - dw) / 2, oy = (sh - dh) / 2
        var g = item.mapToItem(null, 0, 0)
        var gx = win.x - Screen.virtualX + g.x, gy = win.y - Screen.virtualY + g.y
        return Qt.vector4d((gx - ox) / dw, (gy - oy) / dh, item.width / dw, item.height / dh)
    }


    component Glass: ShaderEffect {
        id: g
        property Window win
        property real margin: 28
        property real radius: 20
        property vector2d itemSize: Qt.vector2d(width, height)
        property vector4d shapeRect: Qt.vector4d(margin, margin, width - 2 * margin, height - 2 * margin)
        property real intensity: root.intensity
        property real blur: 1.0
        property real refraction: 1.0
        property real shine: 1.0
        property real tintOpacity: 0.28
        property color tintColor: "#1c1c22"
        property vector4d backdropRect: root.backdropRect(win, g)
        property real dpr: win ? win.devicePixelRatio : 1
        property real shadowStrength: 1.0
        property real darkMode: 1.0
        property real backdropLod: 8
        property vector4d accentGlow: Qt.vector4d(0, 0, 0, 0)
        property variant backdrop
        fragmentShader: "file:///__SHADER__"
    }

    property Window topWin: Window {
        id: top
        objectName: "topWindow"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        x: Screen.virtualX; y: Screen.virtualY
        width: Screen.width; height: 260
        visible: true
        Image { id: wallTop; source: root.wallpaper; visible: false; mipmap: true
                onStatusChanged: if (status === Image.Ready) root.wallSize = Qt.size(sourceSize.width, sourceSize.height) }
        Glass {
            id: pill
            backdrop: wallTop
            win: top
            // Continuous expand/collapse so every vsync has work (idle gaps would skew pacing).
            property real phase: 0
            NumberAnimation on phase { from: 0; to: 1; duration: 1100; loops: Animation.Infinite; easing.type: Easing.SineCurve }
            width: 230 + 330 * phase + 2 * margin
            height: 38 + 132 * phase + 2 * margin
            radius: 19 + 15 * phase
            x: (top.width - width) / 2; y: 8 - margin
            Text { anchors.centerIn: parent; color: "white"; text: "Now Playing"; font.pixelSize: 15; font.weight: Font.DemiBold }
        }
    }

    property Window dockWin: Window {
        id: dock
        objectName: "dockWindow"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        width: 980; height: 170
        x: Screen.virtualX + (Screen.width - width) / 2; y: Screen.virtualY + Screen.height - height
        visible: true
        Image { id: wallDock; source: root.wallpaper; visible: false; mipmap: true }
        Glass {
            id: dockGlass
            backdrop: wallDock
            win: dock
            radius: 26
            width: 860 + 2 * margin; height: 76 + 2 * margin
            x: (dock.width - width) / 2; y: dock.height - height - 6
        }
        Row {
            spacing: 12
            anchors.horizontalCenter: parent.horizontalCenter
            y: dockGlass.y + dockGlass.margin + 10
            Repeater {
                model: 13
                Rectangle {
                    id: icon
                    width: 56; height: 56; radius: 14
                    gradient: Gradient { GradientStop { position: 0; color: Qt.hsla(index / 13, 0.65, 0.62, 1) }
                                         GradientStop { position: 1; color: Qt.hsla(index / 13, 0.7, 0.45, 1) } }
                    property real wave: 0
                    NumberAnimation on wave { from: 0; to: 2 * Math.PI; duration: 1400; loops: Animation.Infinite }
                    property real s: 1 + 0.11 * (1 + Math.sin(wave - index * 0.45))
                    transform: Scale { origin.x: 28; origin.y: 56; xScale: icon.s; yScale: icon.s }
                }
            }
        }
    }
}
"""


def wallpaper_path() -> Path | None:
    p = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
    return p if p.exists() else None


class FrameMeter:
    def __init__(self, window: QQuickWindow):
        self.stamps: list[float] = []
        window.frameSwapped.connect(lambda: self.stamps.append(time.perf_counter()))

    def reset(self):
        self.stamps.clear()

    def stats(self) -> dict:
        iv = [(b - a) * 1000 for a, b in zip(self.stamps, self.stamps[1:])]
        if len(iv) < 5:
            return {"frames": len(self.stamps)}
        iv.sort()
        span = self.stamps[-1] - self.stamps[0]
        return {
            "frames": len(self.stamps),
            "fps": round((len(self.stamps) - 1) / span, 1),
            "median_ms": round(statistics.median(iv), 2),
            "p95_ms": round(iv[int(len(iv) * 0.95)], 2),
            "p99_ms": round(iv[int(len(iv) * 0.99)], 2),
            "max_ms": round(iv[-1], 2),
            "missed_vsync_over_12_5ms": sum(1 for x in iv if x > 12.5),
            "missed_vsync_percent": round(100 * sum(1 for x in iv if x > 12.5) / len(iv), 2),
        }


def gdi_capture_benchmark(w=1000, h=230, n=120) -> dict:
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    user32.GetDC.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    user32.GetDC.restype = wintypes.HDC
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        gdi32.BitBlt(mem, 0, 0, w, h, screen, 0, 0, 0x00CC0020)
        gdi32.GdiFlush()
        times.append((time.perf_counter() - t) * 1000)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)
    times.sort()
    return {"region": f"{w}x{h}", "median_ms": round(statistics.median(times), 2), "p95_ms": round(times[int(n * .95)], 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--api", default="d3d11", choices=["d3d11", "d3d12", "opengl"])
    ap.add_argument("--out", default=str(ROOT / "docs" / "perf" / "render_perf.json"))
    args = ap.parse_args()

    api = {"d3d11": QSGRendererInterface.GraphicsApi.Direct3D11,
           "d3d12": QSGRendererInterface.GraphicsApi.Direct3D12,
           "opengl": QSGRendererInterface.GraphicsApi.OpenGL}[args.api]
    QQuickWindow.setGraphicsApi(api)
    QQuickWindow.setDefaultAlphaBuffer(True)
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    qml = QML.replace("__SHADER__", SHADER.as_posix())
    engine.loadData(qml.encode(), QUrl.fromLocalFile(str(ROOT / "perf.qml")))
    root = engine.rootObjects()[0]
    wp = wallpaper_path()
    if wp:
        root.setProperty("wallpaper", QUrl.fromLocalFile(str(wp)))
    top = root.findChild(QQuickWindow, "topWindow")
    dock = root.findChild(QQuickWindow, "dockWindow")
    top_m, dock_m = FrameMeter(top), FrameMeter(dock)
    results: dict = {"api": args.api, "screen_hz": app.primaryScreen().refreshRate(),
                     "dpr": app.primaryScreen().devicePixelRatio(), "wallpaper": bool(wp)}
    phases = [("glass_full_intensity", 1.0), ("base_material_intensity_0", 0.0)]
    state = {"i": 0, "cpu0": 0.0, "wall0": 0.0}

    def start_phase():
        name, val = phases[state["i"]]
        root.setProperty("intensity", val)
        QTimer.singleShot(600, begin_measure)

    def begin_measure():
        top_m.reset(); dock_m.reset()
        state["cpu0"], state["wall0"] = time.process_time(), time.perf_counter()
        QTimer.singleShot(int(args.seconds * 1000), end_phase)

    def end_phase():
        name, _ = phases[state["i"]]
        cpu = time.process_time() - state["cpu0"]
        wall = time.perf_counter() - state["wall0"]
        results[name] = {"top": top_m.stats(), "dock": dock_m.stats(),
                         "process_cpu_percent_of_one_core": round(100 * cpu / wall, 1)}
        state["i"] += 1
        if state["i"] < len(phases):
            start_phase()
        else:
            top.hide(); dock.hide()
            results["gdi_region_capture"] = gdi_capture_benchmark()
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(results, indent=2))
            print(json.dumps(results, indent=2))
            app.quit()

    QTimer.singleShot(800, start_phase)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
