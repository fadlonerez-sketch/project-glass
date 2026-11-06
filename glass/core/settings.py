"""The single authoritative settings store (owned by the Shell; the Control Center edits it over IPC).

Settings are flat dotted keys (``glass.intensity``) with a declared type, default and constraint. A patch
validates and writes every key *independently*: changing one key never rewrites another (this is what
keeps the Liquid Glass sliders independent of the master intensity). Values are persisted in SQLite.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from glass.core import colors
from glass.core.db import Database

log = logging.getLogger(__name__)


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    kind: str                      # bool | float | int | enum | color | str | colors | widgets | dict | coord | symbols
    default: Any
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()
    label: str = ""
    max_len: int = 200

    def coerce(self, key: str, value: Any) -> Any:
        k = self.kind
        try:
            if k == "bool":
                if isinstance(value, bool):
                    return value
                if value in (0, 1):
                    return bool(value)
                raise SettingsError(f"{key} must be true or false")
            if k in ("float", "int"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise SettingsError(f"{key} must be a number")
                v = float(value) if k == "float" else int(round(float(value)))
                if v != v:  # NaN
                    raise SettingsError(f"{key} must be a number")
                if self.lo is not None and v < self.lo or self.hi is not None and v > self.hi:
                    raise SettingsError(f"{key} must be between {self.lo:g} and {self.hi:g}")
                return round(v, 4) if k == "float" else v
            if k == "coord":
                if value is None:
                    return None
                v = float(value)
                if self.lo is not None and v < self.lo or self.hi is not None and v > self.hi:
                    raise SettingsError(f"{key} is out of range")
                return round(v, 5)
            if k == "enum":
                if value not in self.choices:
                    raise SettingsError(f"{key} must be one of: {', '.join(self.choices)}")
                return value
            if k == "color":
                return colors.parse_hex(value)
            if k == "str":
                if not isinstance(value, str):
                    raise SettingsError(f"{key} must be text")
                return value.strip()[: self.max_len]
            if k == "colors":
                if not isinstance(value, list):
                    raise SettingsError(f"{key} must be a list of colours")
                out: list[str] = []
                for c in value:
                    h = colors.parse_hex(c)
                    if h not in out:
                        out.append(h)
                return out[: int(self.hi or 24)]
            if k == "widgets":
                return _coerce_widgets(key, value)
            if k == "symbols":
                return _coerce_symbols(key, value, int(self.hi or 12))
            if k == "dict":
                if not isinstance(value, dict):
                    raise SettingsError(f"{key} must be an object")
                json.dumps(value)
                return copy.deepcopy(value)
        except colors.ColorError as exc:
            raise SettingsError(f"{key}: {exc}") from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SettingsError):
                raise
            raise SettingsError(f"{key}: invalid value ({exc})") from exc
        raise SettingsError(f"{key}: unknown setting type {k}")


WIDGET_TYPES = ("weather", "calendar", "system", "garvis", "clock")


def _coerce_widgets(key: str, value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise SettingsError(f"{key} must be a list of widgets")
    out, seen = [], set()
    for w in value:
        if not isinstance(w, dict) or w.get("type") not in WIDGET_TYPES:
            raise SettingsError(f"{key}: unknown widget {w!r}")
        wid = str(w.get("id") or f"{w['type']}-{len(out) + 1}")
        if wid in seen:
            raise SettingsError(f"{key}: duplicate widget id {wid}")
        seen.add(wid)
        out.append({"id": wid, "type": w["type"], "config": dict(w.get("config") or {})})
    if len(out) > 6:
        raise SettingsError(f"{key}: at most 6 widgets keep the Dock focused on applications")
    return out


_SYMBOL_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=")


def _coerce_symbols(key: str, value: Any, limit: int) -> list[str]:
    """Ticker symbols: upper-case, de-duplicated, only the characters exchanges use."""
    if not isinstance(value, list):
        raise SettingsError(f"{key} must be a list of symbols")
    out: list[str] = []
    for raw in value:
        sym = str(raw).strip().upper()
        if not sym or len(sym) > 15 or not set(sym) <= _SYMBOL_CHARS:
            raise SettingsError(f"{key}: {raw!r} is not a valid symbol")
        if sym not in out:
            out.append(sym)
    if len(out) > limit:
        raise SettingsError(f"{key}: at most {limit} symbols keep the top bar calm")
    return out


SPECS: dict[str, Spec] = {
    # Appearance
    "appearance.theme": Spec("enum", "adaptive", choices=("adaptive", "light", "dark")),
    "appearance.accent": Spec("color", colors.DEFAULT_ACCENT),
    "appearance.saved_colors": Spec("colors", [], hi=24),
    "appearance.transparency": Spec("float", 0.6, 0.0, 1.0),
    "appearance.accent_tint": Spec("float", 0.0, 0.0, 1.0),      # how much surfaces pick up the accent hue
    "appearance.reduce_motion": Spec("bool", False),
    "appearance.animation_speed": Spec("float", 1.0, 0.5, 2.0),
    # Liquid Glass (master + independent effects). Defaults are the Crystal Glass preset at 100%.
    "glass.intensity": Spec("float", 1.0, 0.0, 1.0),
    "glass.blur": Spec("float", 1.0, 0.0, 1.0),
    "glass.refraction": Spec("float", 1.0, 0.0, 1.0),
    "glass.shine": Spec("float", 1.0, 0.0, 1.0),
    "glass.frost": Spec("float", 0.12, 0.0, 1.0),                 # material appearance: clear .. frosted
    "glass.edge": Spec("float", 0.8, 0.0, 1.0),                   # edge treatment: hairline + rim light
    "glass.depth": Spec("float", 0.7, 0.0, 1.0),                  # visual depth: shadow + elevation
    "glass.accent_tint": Spec("bool", True),                      # the accent colour tints the glass body
    "glass.tint_strength": Spec("float", 0.4, 0.0, 1.0),
    # Top bar / Dynamic Glass
    "topbar.visible": Spec("bool", True),
    "topbar.size": Spec("enum", "regular", choices=("compact", "regular", "large")),
    "topbar.displays": Spec("enum", "primary", choices=("primary", "all")),
    "topbar.animation": Spec("enum", "fluid", choices=("fluid", "gentle", "minimal")),
    "topbar.show_app_name": Spec("bool", True),
    "topbar.background": Spec("enum", "bar", choices=("bar", "floating")),
    "topbar.media.enabled": Spec("bool", True),
    "topbar.media.artwork": Spec("bool", True),
    "topbar.media.progress": Spec("bool", True),
    "topbar.media.visualizer": Spec("bool", True),
    "topbar.media.hover_expand": Spec("bool", True),
    "topbar.media.expand_delay_ms": Spec("int", 100, 0, 1500),
    "topbar.media.collapse_delay_ms": Spec("int", 450, 100, 5000),
    "topbar.island_display": Spec("enum", "active", choices=("active", "primary")),
    "topbar.indicators.battery": Spec("bool", True),
    "topbar.indicators.battery_percent": Spec("bool", True),
    "topbar.indicators.network": Spec("bool", True),
    "topbar.indicators.audio": Spec("bool", True),
    "topbar.indicators.tray": Spec("bool", True),
    "topbar.indicators.clock": Spec("bool", True),
    "topbar.clock.format": Spec("enum", "24h", choices=("24h", "12h")),
    "topbar.clock.show_date": Spec("bool", True),
    "topbar.clock.show_seconds": Spec("bool", False),
    "topbar.notifications.enabled": Spec("bool", True),
    "topbar.notifications.duration_s": Spec("int", 5, 2, 30),
    # Dock
    "dock.visible": Spec("bool", True),
    "dock.position": Spec("enum", "bottom", choices=("bottom", "left", "right")),
    "dock.icon_size": Spec("int", 38, 28, 64),
    "dock.spacing": Spec("int", 10, 4, 24),
    "dock.magnification": Spec("bool", True),
    "dock.magnification_scale": Spec("float", 1.3, 1.0, 1.6),
    "dock.previews": Spec("bool", True),                           # hover an open app to see its windows
    "dock.hover_delay_ms": Spec("int", 150, 60, 600),
    "dock.dismiss_delay_ms": Spec("int", 300, 150, 1000),
    "dock.autohide": Spec("bool", False),
    "dock.show_recent": Spec("bool", True),
    "dock.recent_limit": Spec("int", 6, 0, 20),
    "dock.indicators": Spec("bool", True),
    "dock.launch_bounce": Spec("bool", True),
    "dock.all_desktops": Spec("bool", False),
    "dock.show_launcher": Spec("bool", True),
    "dock.widgets": Spec("widgets", [{"id": "weather-1", "type": "weather", "config": {}}]),
    # Notifications
    "notifications.enabled": Spec("bool", True),
    "notifications.dnd": Spec("bool", False),
    "notifications.mirror_windows": Spec("bool", True),
    "notifications.presentation": Spec("enum", "island", choices=("island", "banner", "silent")),
    "notifications.min_priority": Spec("enum", "normal", choices=("low", "normal", "high")),
    "notifications.apps": Spec("dict", {}),
    "notifications.garvis": Spec("bool", True),
    # Markets (top bar, beside the Dynamic Glass)
    "markets.enabled": Spec("bool", True),
    "markets.watchlist": Spec("symbols", ["AAPL", "MSFT", "NVDA"], hi=12),
    "markets.indices": Spec("symbols", ["^GSPC", "^IXIC", "^DJI"], hi=6),
    "markets.show_indices": Spec("bool", True),
    "markets.refresh_s": Spec("int", 180, 60, 1800),
    "markets.sparklines": Spec("bool", True),
    # System
    "system.enabled": Spec("bool", True),                          # the master power switch (real state)
    "system.start_with_windows": Spec("bool", False),
    "system.hide_taskbar": Spec("bool", True),
    "system.reserve_space": Spec("bool", True),
    "system.live_backdrop": Spec("bool", False),
    # Weather
    "weather.enabled": Spec("bool", True),
    "weather.city": Spec("str", ""),
    "weather.label": Spec("str", ""),
    "weather.latitude": Spec("coord", None, -90, 90),
    "weather.longitude": Spec("coord", None, -180, 180),
    "weather.units": Spec("enum", "c", choices=("c", "f")),
    "weather.details": Spec("bool", True),
    # Garvis
    "garvis.indicator": Spec("bool", True),
    "garvis.notifications": Spec("bool", True),
}

SECTIONS = sorted({k.split(".", 1)[0] for k in SPECS})


def defaults() -> dict[str, Any]:
    return {k: copy.deepcopy(s.default) for k, s in SPECS.items()}


def nest(flat: dict[str, Any]) -> dict:
    out: dict = {}
    for key, value in flat.items():
        node = out
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    return out


_MIGRATIONS = [
    ["CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"],
]


@dataclass
class PatchResult:
    changed: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class SettingsStore:
    """Thread-safe store. Listeners get ``(changed: dict[key, value])`` after each successful write."""

    def __init__(self, path: Path):
        self.db = Database(path, _MIGRATIONS) if not isinstance(path, Database) else path
        self._lock = threading.RLock()
        self._values = defaults()
        self._listeners: list[Callable[[dict], None]] = []
        self.reset_keys: list[str] = []  # stored values that were invalid and fell back to defaults
        self._load()

    def _load(self) -> None:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            spec = SPECS.get(row["key"])
            if spec is None:
                continue  # setting from a newer/older version; ignored, kept on disk
            try:
                self._values[row["key"]] = spec.coerce(row["key"], json.loads(row["value"]))
            except (SettingsError, json.JSONDecodeError) as exc:
                log.warning("Setting %s reset to default: %s", row["key"], exc)
                self.reset_keys.append(row["key"])

    # ------------------------------------------------------------------ reads
    def get(self, key: str) -> Any:
        if key not in SPECS:
            raise SettingsError(f"unknown setting {key}")
        with self._lock:
            return copy.deepcopy(self._values[key])

    def all(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._values)

    def section(self, name: str) -> dict[str, Any]:
        prefix = name + "."
        with self._lock:
            return {k: copy.deepcopy(v) for k, v in self._values.items() if k.startswith(prefix)}

    # ------------------------------------------------------------------ writes
    def patch(self, values: dict[str, Any]) -> PatchResult:
        """Validate each key on its own; valid keys are written even if others fail."""
        result = PatchResult()
        accepted: dict[str, Any] = {}
        for key, raw in values.items():
            spec = SPECS.get(key)
            if spec is None:
                result.errors[key] = f"unknown setting {key}"
                continue
            try:
                accepted[key] = spec.coerce(key, raw)
            except SettingsError as exc:
                result.errors[key] = str(exc)
        with self._lock:
            for key, value in accepted.items():
                if self._values[key] != value:
                    result.changed[key] = value
            if result.changed:
                with self.db.transaction() as conn:
                    conn.executemany(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        [(k, json.dumps(v)) for k, v in result.changed.items()],
                    )
                self._values.update(copy.deepcopy(result.changed))
        if result.changed:
            self._notify(result.changed)
        return result

    def reset(self, keys: list[str] | None = None, section: str | None = None) -> PatchResult:
        if section:
            keys = [k for k in SPECS if k.startswith(section + ".")]
        keys = keys or list(SPECS)
        return self.patch({k: copy.deepcopy(SPECS[k].default) for k in keys if k in SPECS})

    def subscribe(self, listener: Callable[[dict], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _notify(self, changed: dict) -> None:
        for listener in list(self._listeners):
            try:
                listener(copy.deepcopy(changed))
            except Exception:  # a broken listener must not break persistence
                log.exception("settings listener failed")
