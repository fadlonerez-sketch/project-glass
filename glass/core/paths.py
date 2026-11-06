"""Where Project Glass keeps its data. `GLASS_DATA_DIR` overrides the location (tests use it)."""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
QML_DIR = PACKAGE_DIR / "ui" / "qml"
SHADER_DIR = PACKAGE_DIR / "ui" / "shaders"


def data_dir() -> Path:
    override = os.environ.get("GLASS_DATA_DIR")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ProjectGlass"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub_dir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_db() -> Path:
    return data_dir() / "settings.db"


def apps_db() -> Path:
    return data_dir() / "apps.db"


def automation_db() -> Path:
    return sub_dir("automation") / "automation.db"


def secrets_dir() -> Path:
    return sub_dir("secrets")


def logs_dir() -> Path:
    return sub_dir("logs")


def cache_dir() -> Path:
    return sub_dir("cache")


def state_file() -> Path:
    """Recovery state shared by the shell and the watchdog (what to restore on failure)."""
    return data_dir() / "recovery-state.json"


def theme_file() -> Path:
    """Resolved appearance tokens published for other apps (LaunchDeck reads this)."""
    return data_dir() / "theme.json"
