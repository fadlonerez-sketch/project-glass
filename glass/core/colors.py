"""Colour parsing, conversion and accent-tone generation (sRGB, WCAG contrast)."""
from __future__ import annotations

import colorsys
import re

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DEFAULT_ACCENT = "#8E5CF7"  # Glass Violet

# Curated accent presets: name, hex. Distinct hues with matched perceived brightness.
PRESETS: tuple[tuple[str, str], ...] = (
    ("Violet", "#8E5CF7"),
    ("Indigo", "#5E6AD2"),
    ("Blue", "#2F7CF6"),
    ("Sky", "#22A6E8"),
    ("Teal", "#14B8A6"),
    ("Mint", "#34C38F"),
    ("Green", "#3DAA4D"),
    ("Lime", "#8CBF26"),
    ("Yellow", "#E9B824"),
    ("Orange", "#F28C28"),
    ("Coral", "#F2665A"),
    ("Red", "#E5484D"),
    ("Pink", "#E54C9A"),
    ("Magenta", "#C04CDB"),
    ("Graphite", "#8A8F98"),
)


class ColorError(ValueError):
    pass


def parse_hex(text: str) -> str:
    """Normalise '#abc', 'abc', '#AABBCC' to '#AABBCC'."""
    m = _HEX.match(str(text).strip())
    if not m:
        raise ColorError(f"'{text}' is not a hex colour like #8E5CF7")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def is_hex(text: str) -> bool:
    try:
        parse_hex(text)
        return True
    except ColorError:
        return False


def to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = parse_hex(hex_color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def from_rgb(r: int, g: int, b: int) -> str:
    for v in (r, g, b):
        if not (0 <= int(v) <= 255):
            raise ColorError("RGB components must be between 0 and 255")
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))


def to_hsl(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in to_rgb(hex_color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s, l


def from_hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return from_rgb(round(r * 255), round(g * 255), round(b * 255))


def to_hsv(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in to_rgb(hex_color))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s, v


def from_hsv(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return from_rgb(round(r * 255), round(g * 255), round(b * 255))


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = to_rgb(a)
    rb, gb, bb = to_rgb(b)
    t = max(0.0, min(1.0, t))
    return from_rgb(round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def luminance(hex_color: str) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = to_rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(background: str) -> str:
    """White or near-black text, whichever contrasts better with the background."""
    return "#FFFFFF" if contrast("#FFFFFF", background) >= contrast("#111114", background) else "#111114"


def accent_tones(accent: str, dark: bool) -> dict[str, str]:
    """Hover/pressed/soft variants that keep the hue and stay legible in the given mode."""
    accent = parse_hex(accent)
    h, s, l = to_hsl(accent)
    # Very dark accents on dark surfaces (and very light ones on light surfaces) are lifted for legibility.
    if dark and l < 0.45:
        l = 0.45 + (l * 0.2)
    if not dark and l > 0.62:
        l = 0.62 - ((1 - l) * 0.2)
    base = from_hsl(h, s, l)
    return {
        "accent": base,
        "accent_hover": from_hsl(h, s, min(1.0, l + (0.06 if dark else -0.05))),
        "accent_pressed": from_hsl(h, s, max(0.0, l + (-0.06 if dark else -0.10))),
        "accent_soft": mix(base, "#1A1A1F" if dark else "#FFFFFF", 0.78 if dark else 0.84),
        "accent_text": ensure_contrast(from_hsl(h, min(1.0, s), 0.74 if dark else 0.42),
                                       "#1D1D22" if dark else "#FFFFFF", 4.5),
        "on_accent": readable_on(base),
    }


def ensure_contrast(color: str, background: str, target: float = 4.5) -> str:
    """Shift lightness (keeping hue and saturation) until the colour reaches the contrast target."""
    h, s, l = to_hsl(color)
    step = 0.02 if luminance(background) < 0.5 else -0.02
    for _ in range(60):
        candidate = from_hsl(h, s, l)
        if contrast(candidate, background) >= target or not (0.0 < l < 1.0):
            return candidate
        l = max(0.0, min(1.0, l + step))
    return from_hsl(h, s, l)
