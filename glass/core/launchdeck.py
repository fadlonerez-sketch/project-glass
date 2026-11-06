"""Integration with LaunchDeck (the existing launcher, ~/LaunchDeck). Glass never edits LaunchDeck's data.

* ``data_dir()`` / ``instance_name()`` mirror LaunchDeck's own rules so Glass can reach the running
  instance over its single-instance pipe and send ``launcher`` (open the search) or ``settings``.
* ``usage_history()`` reads LaunchDeck's usage table read-only, to seed the Dock's Recently Used list on
  first run (only application shortcuts and Store apps, never files or websites).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("LAUNCHDECK_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "LaunchDeck"


def instance_name(directory: Path | None = None) -> str:
    d = str(directory or data_dir())
    digest = hashlib.sha1(os.path.normcase(os.path.abspath(d)).encode("utf-8")).hexdigest()[:12]
    return f"LaunchDeck-{digest}"


def pipe_path(directory: Path | None = None) -> str:
    return "\\\\.\\pipe\\" + instance_name(directory)


def project_dir() -> Path:
    return Path(os.environ.get("LAUNCHDECK_HOME", Path.home() / "LaunchDeck"))


def is_installed() -> bool:
    return (project_dir() / "main.py").exists()


def send(message: str, directory: Path | None = None, timeout: float = 1.5) -> bool:
    """Write one request to the running LaunchDeck instance. Returns False if it isn't running."""
    deadline = time.monotonic() + timeout
    path = pipe_path(directory)
    while True:
        try:
            with open(path, "wb", buffering=0) as pipe:
                pipe.write(message.encode("utf-8"))
            return True
        except FileNotFoundError:
            return False
        except OSError:  # ERROR_PIPE_BUSY: another client is mid-request
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)


@dataclass(frozen=True)
class UsageEntry:
    target: str        # .lnk path or shell:AppsFolder\<AUMID>
    count: int
    last_used: float

    @property
    def is_packaged(self) -> bool:
        return self.target.lower().startswith("shell:appsfolder\\")


def usage_history(directory: Path | None = None, limit: int = 40) -> list[UsageEntry]:
    db = (directory or data_dir()) / "data.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT key, count, last_used FROM usage WHERE key LIKE 'app:%' ORDER BY last_used DESC LIMIT ?",
            (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for key, count, last_used in rows:
        target = key[4:]
        if target.lower().endswith((".lnk", ".exe", ".appref-ms")) or target.lower().startswith("shell:appsfolder\\"):
            out.append(UsageEntry(target, int(count), float(last_used)))
    return out
