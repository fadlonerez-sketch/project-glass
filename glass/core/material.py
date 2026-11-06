"""Liquid Glass material model -- how settings become shader uniforms.

Rendering rule (documented in docs/LIQUID_GLASS.md):

* ``intensity`` is a master multiplier applied *inside the shader*: every glass effect's visible
  contribution is ``effect_value x intensity``. Stored effect values are never modified by it.
* At intensity 0 the surface is exactly the base theme material: an opaque tint with its hairline edge and
  shadow (governed by ``edge`` and ``depth``, which belong to the base material). Blur, refraction,
  specular shine and the accent tint contribute nothing, yet keep their configured values.
* As intensity rises, the tint becomes translucent (down to the opacity set by Appearance > Transparency
  and Glass > Frost), the backdrop is blurred by ``blur``, bent at the bevel by ``refraction`` (with
  chromatic dispersion), lit by ``shine``, and -- when the accent tint is on -- coloured by the accent in
  proportion to ``tint_strength``.

Presets are named sets of these values. Choosing one writes its values (each still independently
adjustable afterwards); ``matching_preset`` reports which preset the current values equal, if any.
"""
from __future__ import annotations

from typing import Any

from glass.core import colors

PRESETS: dict[str, dict[str, Any]] = {
    # Quiet, frosted, barely-there distortion: glass as a calm surface.
    "subtle": {"glass.intensity": 0.6, "glass.blur": 0.9, "glass.refraction": 0.35, "glass.shine": 0.45,
               "glass.frost": 0.55, "glass.edge": 0.5, "glass.depth": 0.45, "glass.accent_tint": True,
               "glass.tint_strength": 0.2},
    # Fluid and lens-like: strong edge lensing over a softer blur, gentle highlights.
    "liquid": {"glass.intensity": 0.85, "glass.blur": 0.65, "glass.refraction": 0.9, "glass.shine": 0.75,
               "glass.frost": 0.28, "glass.edge": 0.65, "glass.depth": 0.6, "glass.accent_tint": True,
               "glass.tint_strength": 0.32},
    # Clear and brilliant: everything at full strength, crisp rims, deep shadow (the default).
    "crystal": {"glass.intensity": 1.0, "glass.blur": 1.0, "glass.refraction": 1.0, "glass.shine": 1.0,
                "glass.frost": 0.12, "glass.edge": 0.8, "glass.depth": 0.7, "glass.accent_tint": True,
                "glass.tint_strength": 0.4},
}
PRESET_NAMES = {"subtle": "Subtle Glass", "liquid": "Liquid Glass", "crystal": "Crystal Glass"}


def matching_preset(values: dict[str, Any], tolerance: float = 0.006) -> str:
    """The preset whose values the settings currently equal, else ``"custom"``."""
    for name, preset in PRESETS.items():
        same = True
        for key, want in preset.items():
            have = values.get(key)
            if isinstance(want, bool):
                same = bool(have) == want
            else:
                same = have is not None and abs(float(have) - want) <= tolerance
            if not same:
                break
        if same:
            return name
    return "custom"


def tint_opacity(transparency: float, frost: float) -> float:
    """Opacity of the tint layer when intensity is 1 (0 = fully clear glass, 1 = opaque)."""
    base = 0.14 + 0.62 * (1.0 - transparency)
    return round(max(0.06, min(0.95, base + 0.22 * frost)), 4)


def uniforms(values: dict[str, Any], tok: dict[str, Any]) -> dict[str, Any]:
    dark = bool(tok.get("dark"))
    frost = float(values.get("glass.frost", 0.12))
    tint = tok["glass_tint"]
    # Frost whitens (light) / lifts (dark) the tint, like sandblasted glass scattering more light.
    tint = colors.mix(tint, "#FFFFFF" if not dark else "#3A3A44", 0.35 * frost)
    strength = float(values.get("glass.tint_strength", 0.4)) if values.get("glass.accent_tint", True) else 0.0
    return {
        "intensity": float(values.get("glass.intensity", 1.0)),
        "blur": float(values.get("glass.blur", 1.0)),
        "refraction": float(values.get("glass.refraction", 1.0)),
        "shine": float(values.get("glass.shine", 1.0)),
        "edge": float(values.get("glass.edge", 0.8)),
        "depth": float(values.get("glass.depth", 0.7)),
        "frost": frost,
        "tintOpacity": tint_opacity(float(values.get("appearance.transparency", 0.6)), frost),
        "tintColor": tint,
        "accentColor": tok.get("accent", colors.DEFAULT_ACCENT),
        "tintStrength": round(strength, 4),
        "baseColor": tok["base_material"],
        "darkMode": 1.0 if dark else 0.0,
        "preset": matching_preset(values),
    }


def effective(values: dict[str, Any]) -> dict[str, float]:
    """The visible strength of each effect (what the user actually sees), for previews and docs."""
    i = float(values.get("glass.intensity", 1.0))
    tint = float(values.get("glass.tint_strength", 0.4)) if values.get("glass.accent_tint", True) else 0.0
    return {
        "blur": round(float(values.get("glass.blur", 1.0)) * i, 4),
        "refraction": round(float(values.get("glass.refraction", 1.0)) * i, 4),
        "shine": round(float(values.get("glass.shine", 1.0)) * i, 4),
        "tint": round(tint * i, 4),
        "translucency": round(i, 4),
    }
