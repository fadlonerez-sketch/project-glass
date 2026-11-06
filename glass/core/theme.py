"""Design tokens: one resolved palette for every Glass surface (and LaunchDeck, via theme.json).

Both appearances are designed deliberately, not derived by inverting one another. Colours with alpha use
Qt's ``#AARRGGBB`` form.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from glass.core import colors

FONT_DISPLAY = "Segoe UI Variable Display"
FONT_TEXT = "Segoe UI Variable Text"
FONT_FALLBACK = "Segoe UI"

_LIGHT = {
    "bg": "#F3F3F6",
    "surface": "#FFFFFF",
    "surface2": "#F2F2F5",
    "surface3": "#E9E9EE",
    "base_material": "#F6F6F9",
    "glass_tint": "#FBFBFD",
    "text": "#16161A",
    "text2": "#5A5A64",
    "text3": "#8B8B96",
    "separator": "#16000000",
    "hairline": "#12000000",
    "control": "#0D000000",
    "control_hover": "#16000000",
    "control_pressed": "#20000000",
    "track": "#1C000000",
    "shadow": "#33000000",
    "scrim": "#22000000",
    "success": "#2FA45B",
    "warning": "#D9921A",
    "danger": "#E0443E",
}

_DARK = {
    "bg": "#131317",
    "surface": "#1D1D22",
    "surface2": "#25252B",
    "surface3": "#2E2E35",
    "base_material": "#1B1B20",
    "glass_tint": "#1E1E24",
    "text": "#F4F4F7",
    "text2": "#A6A6B0",
    "text3": "#6E6E79",
    "separator": "#1CFFFFFF",
    "hairline": "#14FFFFFF",
    "control": "#12FFFFFF",
    "control_hover": "#1CFFFFFF",
    "control_pressed": "#26FFFFFF",
    "track": "#26FFFFFF",
    "shadow": "#73000000",
    "scrim": "#44000000",
    "success": "#45C47A",
    "warning": "#F0B13D",
    "danger": "#F2635D",
}


def resolve_mode(theme_setting: str, system_dark: bool) -> str:
    if theme_setting == "light":
        return "light"
    if theme_setting == "dark":
        return "dark"
    return "dark" if system_dark else "light"


def tokens(values: dict[str, Any], system_dark: bool) -> dict[str, Any]:
    """Resolve the palette from settings values (flat dotted keys)."""
    mode = resolve_mode(values.get("appearance.theme", "adaptive"), system_dark)
    dark = mode == "dark"
    t = dict(_DARK if dark else _LIGHT)
    accent = values.get("appearance.accent", colors.DEFAULT_ACCENT)
    t.update(colors.accent_tones(accent, dark))
    tint = float(values.get("appearance.accent_tint", 0.0))
    if tint > 0:
        # Surfaces pick up a whisper of the accent hue; capped so text contrast is never compromised.
        amount = 0.10 * tint
        for key in ("bg", "surface", "surface2", "base_material", "glass_tint"):
            t[key] = colors.mix(t[key], t["accent"], amount)
    t["mode"] = mode
    t["dark"] = dark
    t["font_display"] = FONT_DISPLAY
    t["font_text"] = FONT_TEXT
    t["font_fallback"] = FONT_FALLBACK
    t["reduce_motion"] = bool(values.get("appearance.reduce_motion", False))
    t["animation_speed"] = float(values.get("appearance.animation_speed", 1.0))
    return t


def write_theme_file(path: Path, tok: dict[str, Any]) -> None:
    """Publish the resolved appearance for other apps (LaunchDeck). Atomic replace."""
    keys = ("mode", "accent", "accent_hover", "accent_pressed", "accent_soft", "accent_text", "on_accent",
            "bg", "surface", "surface2", "surface3", "text", "text2", "text3", "separator", "control",
            "control_hover", "success", "warning", "danger", "font_display", "font_text")
    payload = {"version": 1, "source": "Project Glass", "updated": time.time(),
               **{k: tok[k] for k in keys if k in tok}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
