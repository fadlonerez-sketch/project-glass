"""Glyph rendering for QML: ``image://glyph/<spec>`` -> crisp vector icons rasterised at device resolution.

The path data lives in qml/components/Glyphs.js (one source of truth). Composite status glyphs (Wi-Fi
strength, speaker level, weather) are assembled here. Rendering through QSvgRenderer into an image keeps
icons correct across live theme switches (Qt 6.11's curve renderer skipped some recolours).

Spec forms (URL-encoded colours, '#' -> '%23'):
    icon/<name>/<color>/<stroke>
    wifi/<level 0-3>/<kind>/<color>
    speaker/<level 0-1>/<muted 0|1>/<color>
    weather/<kind>/<day 0|1>/<dark 0|1>
"""
from __future__ import annotations

import re
import threading
from urllib.parse import unquote

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

from glass.core import paths

_ENTRY = re.compile(r'"([\w-]+)"\s*:\s*\{([^}]*)\}')
_FIELD = re.compile(r'(\w)\s*:\s*"([^"]*)"')


def load_glyphs() -> dict[str, dict[str, str]]:
    text = (paths.QML_DIR / "components" / "Glyphs.js").read_text(encoding="utf-8")
    return {name: dict(_FIELD.findall(body)) for name, body in _ENTRY.findall(text)}


GLYPHS = load_glyphs()


def _svg(parts: list[tuple[str, str, str, float]], stroke: float = 2.27, view: int = 24) -> str:
    """parts: (path d, 'stroke'|'fill', colour, opacity)."""
    body = []
    for d, kind, color, op in parts:
        if not d:
            continue
        if kind == "stroke":
            body.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-opacity="{op}" stroke-width="{stroke}" '
                        f'stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            body.append(f'<path d="{d}" fill="{color}" fill-opacity="{op}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}">{"".join(body)}</svg>'


def icon_svg(name: str, color: str, stroke: float) -> str:
    g = GLYPHS.get(name, {})
    return _svg([(g.get("s", ""), "stroke", color, 1.0), (g.get("f", ""), "fill", color, 1.0)], stroke * 24 / 18)


WIFI = ["M2.8 9.2a13 13 0 0 1 18.4 0", "M6 12.6a8.4 8.4 0 0 1 12 0", "M9.2 16a3.9 3.9 0 0 1 5.6 0"]
WIFI_DOT = "M12 20.6a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"


def wifi_svg(level: int, kind: str, color: str) -> str:
    on = kind == "wifi"
    parts = [(WIFI[0], "stroke", color, 1.0 if on and level >= 3 else 0.28),
             (WIFI[1], "stroke", color, 1.0 if on and level >= 2 else 0.28),
             (WIFI[2], "stroke", color, 1.0 if on and level >= 1 else 0.28),
             (WIFI_DOT, "fill", color, 1.0 if on else 0.28)]
    return _svg(parts, 2.3)


def speaker_svg(level: float, muted: bool, color: str) -> str:
    parts = [(GLYPHS["speaker"]["f"], "fill", color, 1.0)]
    if muted:
        parts.append(("M16.5 9.5l5 5M21.5 9.5l-5 5", "stroke", color, 1.0))
    else:
        parts.append(("M16.2 9.4a3.8 3.8 0 0 1 0 5.2", "stroke", color, 1.0 if level > 0.01 else 0.28))
        parts.append(("M18.8 6.8a7.6 7.6 0 0 1 0 10.4", "stroke", color, 1.0 if level > 0.5 else 0.28))
    return _svg(parts, 2.0)


def weather_svg(kind: str, day: bool, dark: bool) -> str:
    sun, water = "#FFB830", "#4CA6FF"
    cloud, edge = ("#DCDDE6", "#B9BAC6") if dark else ("#F4F5FA", "#C9CBD6")
    has_sun, has_cloud = kind in ("clear", "partly"), kind != "clear"
    parts: list[tuple[str, str, str, float]] = []
    if has_sun:
        if day:
            d = "M12 5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z" if kind == "partly" else "M16 9a7 7 0 1 0 0 14 7 7 0 0 0 0-14z"
            parts.append((d, "fill", sun, 1.0))
            if kind == "clear":
                parts.append(("M16 3v2.5M16 26.5V29M3 16h2.5M26.5 16H29M6.8 6.8l1.8 1.8M23.4 23.4l1.8 1.8M6.8 25.2l1.8-1.8M23.4 8.6l1.8-1.8",
                              "stroke", sun, 1.0))
        else:
            d = "M14 4.5a6.5 6.5 0 1 0 5 10.6A7.5 7.5 0 0 1 14 4.5z" if kind == "partly" else "M18 6a8 8 0 1 0 6 13.3A9 9 0 0 1 18 6z"
            parts.append((d, "fill", "#E9E6D8", 1.0))
    if has_cloud:
        d = ("M12.5 26h12a5 5 0 0 0 .4-10 7 7 0 0 0-13.2 1.6A4.3 4.3 0 0 0 12.5 26z" if kind == "partly"
             else "M9 23h15a5.5 5.5 0 0 0 .5-11 8 8 0 0 0-15.2 2A4.6 4.6 0 0 0 9 23z")
        parts.append((d, "fill", cloud, 1.0))
        parts.append((d, "stroke", edge, 1.0))
    rain = {"drizzle": "M12 26v1.5M17 26v1.5M22 26v1.5", "heavy_rain": "M10.5 25.5 9 29.5M15 25.5l-1.5 4M19.5 25.5 18 29.5M24 25.5l-1.5 4",
            "thunder": "M11 26l-1 3M23 26l-1 3", "rain": "M12 25.5l-1.2 3.5M17 25.5l-1.2 3.5M22 25.5l-1.2 3.5",
            "sleet": "M12 25.5l-1.2 3.5M22 25.5l-1.2 3.5"}
    if kind in rain:
        parts.append((rain[kind], "stroke", water, 1.0))
    if kind in ("snow", "sleet"):
        parts.append(("M11 27.5a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6zM16.5 29a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6zM22 27.5a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6z",
                      "fill", "#FFFFFF" if dark else "#9CC9FF", 1.0))
    if kind == "thunder":
        parts.append(("M17.5 22h-3.6l-1.9 5h3l-1.5 4.5 5.5-6.5h-3z", "fill", "#FFC83A", 1.0))
    if kind == "fog":
        parts.append(("M7 26.5h18M10 29.5h12", "stroke", edge, 1.0))
    return _svg(parts, 2.0, view=32)


def render(spec: str, px: int) -> QImage:
    parts = [unquote(p) for p in spec.split("/")]
    kind = parts[0]
    try:
        if kind == "icon":
            svg = icon_svg(parts[1], parts[2], float(parts[3]) if len(parts) > 3 else 1.7)
        elif kind == "wifi":
            svg = wifi_svg(int(parts[1]), parts[2], parts[3])
        elif kind == "speaker":
            svg = speaker_svg(float(parts[1]), parts[2] == "1", parts[3])
        elif kind == "weather":
            svg = weather_svg(parts[1], parts[2] == "1", parts[3] == "1")
        else:
            return QImage()
    except (IndexError, ValueError, KeyError):
        return QImage()
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    return img


class GlyphProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: dict[tuple[str, int], QImage] = {}
        self._lock = threading.Lock()

    def requestImage(self, ident: str, size: QSize, requested: QSize) -> QImage:
        px = max(8, min(512, requested.width() if requested.width() > 0 else 48))
        key = (ident, px)
        with self._lock:
            img = self._cache.get(key)
        if img is None:
            img = render(ident, px)
            with self._lock:
                if len(self._cache) > 3000:
                    self._cache.clear()
                self._cache[key] = img
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img
