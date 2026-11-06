"""Per-monitor desktop backdrop for the Liquid Glass shader.

The top bar and the Dock sit in work-area strips that Glass reserves, so what is physically behind them is
the desktop wallpaper. Rendering that wallpaper exactly as Windows lays it out (fill/fit/stretch/center/
tile/span, background colour) gives the shader the true backdrop to refract -- with no screen capture.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from glass.win import shellcom

log = logging.getLogger(__name__)


def transcoded_wallpaper() -> str:
    p = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
    return str(p) if p.exists() else ""


def layout_rect(img_w: int, img_h: int, area_w: int, area_h: int, mode: str) -> QRectF:
    """Where Windows draws an img_w x img_h picture inside an area (mode = fill|fit|stretch|center|tile|span)."""
    if mode == "stretch":
        return QRectF(0, 0, area_w, area_h)
    if mode == "center":
        return QRectF((area_w - img_w) / 2, (area_h - img_h) / 2, img_w, img_h)
    if mode == "fit":
        s = min(area_w / img_w, area_h / img_h)
    else:  # fill, span (span is applied to the virtual screen by the caller)
        s = max(area_w / img_w, area_h / img_h)
    w, h = img_w * s, img_h * s
    return QRectF((area_w - w) / 2, (area_h - h) / 2, w, h)


def render_monitor(path: str, mode: str, background: str, size: tuple[int, int],
                   span_offset: tuple[int, int] | None = None, virtual_size: tuple[int, int] | None = None) -> QImage:
    w, h = size
    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(QColor(background or "#000000"))
    img = QImage(path) if path else QImage()
    if img.isNull():
        return out
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if mode == "tile":
        for y in range(0, h, img.height()):
            for x in range(0, w, img.width()):
                p.drawImage(x, y, img)
    elif mode == "span" and span_offset and virtual_size:
        r = layout_rect(img.width(), img.height(), virtual_size[0], virtual_size[1], "fill")
        r.translate(-span_offset[0], -span_offset[1])
        p.drawImage(r, img, QRectF(img.rect()))
    else:
        p.drawImage(layout_rect(img.width(), img.height(), w, h, mode), img, QRectF(img.rect()))
    p.end()
    return out


class BackdropCache:
    """Renders and caches one PNG per monitor; returns file URLs QML can load with mipmaps."""

    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.version = 0
        self._by_rect: dict[tuple, str] = {}

    def refresh(self) -> dict[tuple[int, int, int, int], str]:
        """Physical monitor rect -> backdrop PNG path."""
        self.version += 1
        infos = shellcom.wallpapers()
        if not infos:
            return {}
        vx = min(i["rect"][0] for i in infos)
        vy = min(i["rect"][1] for i in infos)
        vw = max(i["rect"][0] + i["rect"][2] for i in infos) - vx
        vh = max(i["rect"][1] + i["rect"][3] for i in infos) - vy
        result: dict[tuple[int, int, int, int], str] = {}
        for info in infos:
            path = info["path"] if info["path"] and Path(info["path"]).exists() else transcoded_wallpaper()
            x, y, w, h = info["rect"]
            stamp = f"{path}|{os.path.getmtime(path) if path and Path(path).exists() else 0}|{info['position']}|{info['background']}|{info['rect']}"
            key = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16]
            out = self.dir / f"backdrop-{key}.png"
            if not out.exists():
                img = render_monitor(path, info["position"], info["background"], (w, h),
                                     span_offset=(x - vx, y - vy), virtual_size=(vw, vh))
                img.save(str(out), "PNG")
                log.info("rendered backdrop for monitor %s (%s)", info["rect"], info["position"])
            result[(x, y, w, h)] = str(out)
        self._by_rect = result
        # keep the cache small
        keep = set(result.values())
        for old in self.dir.glob("backdrop-*.png"):
            if str(old) not in keep:
                try:
                    old.unlink()
                except OSError:
                    pass
        return result

    def for_monitor(self, rect: tuple[int, int, int, int]) -> str:
        if not self._by_rect:
            self.refresh()
        if rect in self._by_rect:
            return self._by_rect[rect]
        # Nearest by origin (handles transient geometry mismatches during display changes).
        if self._by_rect:
            return min(self._by_rect.items(), key=lambda kv: abs(kv[0][0] - rect[0]) + abs(kv[0][1] - rect[1]))[1]
        return ""
