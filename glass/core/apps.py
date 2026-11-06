"""Application registry and the Dock model.

One source of truth:

* ``AppRegistry`` (SQLite) remembers every application the Dock knows: identity, how to launch it, its
  icon source, pin state/order and launch history.
* The *running set* comes only from the window tracker (``RunningApp`` per app id).
* ``compute_dock`` is a pure, deterministic function of (registry records, running set, options):

  - **Open**: every running app. Pinned ones first in their manual pin order, then unpinned ones in
    launch order (a newly launched app appears at the end, so icons never jump around).
  - **Recently Used**: apps that are *not* running. Pinned ones first in their manual order (never
    dropped, however old), then unpinned ones by most recent launch, capped by ``recent_limit``.

  The Recent section is derived from the running set, never the other way round, and no app id can
  appear twice.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from glass.core.db import Database

_MIGRATIONS = [
    [
        """CREATE TABLE apps (
            app_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            exe TEXT NOT NULL DEFAULT '',
            aumid TEXT NOT NULL DEFAULT '',
            launch TEXT NOT NULL DEFAULT '',
            icon TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            pin_order REAL,
            hidden INTEGER NOT NULL DEFAULT 0,
            last_launched REAL,
            last_closed REAL,
            launch_count INTEGER NOT NULL DEFAULT 0,
            added REAL NOT NULL
        )""",
        "CREATE TABLE aliases (alias TEXT PRIMARY KEY, app_id TEXT NOT NULL)",
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ],
]


def exe_key(path: str) -> str:
    return "exe:" + os.path.normcase(os.path.normpath(path))


def aumid_key(aumid: str) -> str:
    return "aumid:" + aumid.lower()


@dataclass(frozen=True)
class AppRecord:
    app_id: str
    name: str
    exe: str = ""
    aumid: str = ""
    launch: str = ""          # .lnk path, "shell:AppsFolder\\<AUMID>", or an exe path
    icon: str = ""            # icon source (path or parsing name) for the icon provider
    pinned: bool = False
    pin_order: float | None = None
    hidden: bool = False      # removed from Recently Used by the user (reappears when launched again)
    last_launched: float | None = None
    last_closed: float | None = None
    launch_count: int = 0
    added: float = 0.0


@dataclass(frozen=True)
class RunningApp:
    app_id: str
    name: str
    windows: tuple[int, ...]
    focused: bool = False
    first_seen: float = 0.0
    exe: str = ""
    aumid: str = ""


@dataclass(frozen=True)
class DockItem:
    app_id: str
    name: str
    section: str              # "open" | "recent"
    pinned: bool
    running: bool
    focused: bool
    window_count: int
    windows: tuple[int, ...] = ()
    launch: str = ""
    icon: str = ""
    exe: str = ""
    aumid: str = ""


@dataclass
class DockLayout:
    open: list[DockItem] = field(default_factory=list)
    recent: list[DockItem] = field(default_factory=list)

    def ids(self) -> list[str]:
        return [i.app_id for i in self.open] + [i.app_id for i in self.recent]


def compute_dock(records: Iterable[AppRecord], running: dict[str, RunningApp], *,
                 show_recent: bool = True, recent_limit: int = 6, exclude: frozenset[str] | set[str] = frozenset()) -> DockLayout:
    """``exclude``: apps that are running but not shown (e.g. only on another virtual desktop). They are not
    closed, so they must not appear in Recently Used either."""
    recs = {r.app_id: r for r in records}
    layout = DockLayout()

    def pin_key(r: AppRecord) -> tuple:
        return (r.pin_order if r.pin_order is not None else float("inf"), r.name.lower(), r.app_id)

    # --- Open: pinned (manual order) then unpinned by launch time (ascending = stable positions)
    open_pinned, open_other = [], []
    for app_id, run in running.items():
        rec = recs.get(app_id)
        if rec is not None and rec.pinned:
            open_pinned.append((rec, run))
        else:
            open_other.append((rec, run))
    open_pinned.sort(key=lambda pr: pin_key(pr[0]))

    def launch_order(pr) -> tuple:
        rec, run = pr
        started = run.first_seen or (rec.last_launched if rec and rec.last_launched else 0.0)
        return (started, run.name.lower(), run.app_id)

    open_other.sort(key=launch_order)
    for rec, run in open_pinned + open_other:
        layout.open.append(DockItem(
            app_id=run.app_id, name=rec.name if rec else run.name, section="open",
            pinned=bool(rec and rec.pinned), running=True, focused=run.focused,
            window_count=len(run.windows), windows=tuple(run.windows),
            launch=rec.launch if rec else "", icon=(rec.icon if rec and rec.icon else run.exe),
            exe=(rec.exe if rec and rec.exe else run.exe), aumid=(rec.aumid if rec and rec.aumid else run.aumid),
        ))

    # --- Recently Used: never running; pinned first (never capped), then most recent launches
    closed = [r for r in recs.values() if r.app_id not in running and r.app_id not in exclude]
    pinned_closed = sorted((r for r in closed if r.pinned), key=pin_key)
    recent = sorted((r for r in closed if not r.pinned and not r.hidden and r.last_launched),
                    key=lambda r: (-(r.last_launched or 0.0), r.name.lower(), r.app_id))
    recent = recent[: max(0, recent_limit)] if show_recent else []
    for r in pinned_closed + recent:
        layout.recent.append(DockItem(
            app_id=r.app_id, name=r.name, section="recent", pinned=r.pinned, running=False, focused=False,
            window_count=0, launch=r.launch, icon=r.icon or r.exe, exe=r.exe, aumid=r.aumid,
        ))
    return layout


class AppRegistry:
    def __init__(self, path: Path | Database):
        self.db = path if isinstance(path, Database) else Database(path, _MIGRATIONS)

    # ------------------------------------------------------------------ identity
    def resolve(self, keys: Iterable[str]) -> str | None:
        """Map any known identity key (aumid:/exe:) to the registry's app id."""
        keys = [k for k in keys if k]
        if not keys:
            return None
        with self.db.connect() as conn:
            for k in keys:
                row = conn.execute("SELECT app_id FROM apps WHERE app_id = ?", (k,)).fetchone()
                if row:
                    return row["app_id"]
            for k in keys:
                row = conn.execute("SELECT app_id FROM aliases WHERE alias = ?", (k,)).fetchone()
                if row:
                    return row["app_id"]
        return None

    def add_alias(self, alias: str, app_id: str) -> None:
        if alias and alias != app_id:
            with self.db.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO aliases (alias, app_id) VALUES (?, ?)", (alias, app_id))

    # ------------------------------------------------------------------ reads
    def all(self) -> list[AppRecord]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM apps").fetchall()
        return [self._row(r) for r in rows]

    def get(self, app_id: str) -> AppRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(r) -> AppRecord:
        return AppRecord(app_id=r["app_id"], name=r["name"], exe=r["exe"], aumid=r["aumid"], launch=r["launch"],
                         icon=r["icon"], pinned=bool(r["pinned"]), pin_order=r["pin_order"], hidden=bool(r["hidden"]),
                         last_launched=r["last_launched"], last_closed=r["last_closed"],
                         launch_count=r["launch_count"], added=r["added"])

    # ------------------------------------------------------------------ lifecycle events (from the tracker)
    def ensure(self, rec: AppRecord) -> AppRecord:
        """Insert if unknown; fill in missing identity fields without overwriting user choices."""
        existing = self.get(rec.app_id)
        now = time.time()
        with self.db.transaction() as conn:
            if existing is None:
                conn.execute(
                    "INSERT INTO apps (app_id, name, exe, aumid, launch, icon, pinned, pin_order, hidden, "
                    "last_launched, last_closed, launch_count, added) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec.app_id, rec.name, rec.exe, rec.aumid, rec.launch, rec.icon, int(rec.pinned), rec.pin_order,
                     int(rec.hidden), rec.last_launched, rec.last_closed, rec.launch_count, rec.added or now))
            else:
                conn.execute(
                    "UPDATE apps SET exe = CASE WHEN exe = '' THEN ? ELSE exe END, "
                    "aumid = CASE WHEN aumid = '' THEN ? ELSE aumid END, "
                    "launch = CASE WHEN launch = '' THEN ? ELSE launch END, "
                    "icon = CASE WHEN icon = '' THEN ? ELSE icon END WHERE app_id = ?",
                    (rec.exe, rec.aumid, rec.launch, rec.icon, rec.app_id))
        return self.get(rec.app_id)  # type: ignore[return-value]

    def record_launch(self, app_id: str, when: float | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE apps SET last_launched = ?, launch_count = launch_count + 1, hidden = 0 "
                         "WHERE app_id = ?", (when or time.time(), app_id))

    def record_closed(self, app_id: str, when: float | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE apps SET last_closed = ? WHERE app_id = ?", (when or time.time(), app_id))

    # ------------------------------------------------------------------ user customisation
    def pinned(self) -> list[AppRecord]:
        return sorted((r for r in self.all() if r.pinned),
                      key=lambda r: (r.pin_order if r.pin_order is not None else float("inf"), r.name.lower()))

    def pin(self, app_id: str, index: int | None = None) -> None:
        order = [r.app_id for r in self.pinned() if r.app_id != app_id]
        index = len(order) if index is None else max(0, min(index, len(order)))
        order.insert(index, app_id)
        self._write_pin_order(order, also_pin=app_id)

    def unpin(self, app_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE apps SET pinned = 0, pin_order = NULL WHERE app_id = ?", (app_id,))
        self._write_pin_order([r.app_id for r in self.pinned()])

    def move_pinned(self, app_id: str, index: int) -> None:
        order = [r.app_id for r in self.pinned()]
        if app_id not in order:
            raise KeyError(app_id)
        order.remove(app_id)
        order.insert(max(0, min(index, len(order))), app_id)
        self._write_pin_order(order)

    def set_pin_order(self, order: list[str]) -> None:
        pinned = {r.app_id for r in self.pinned()}
        if set(order) != pinned:
            raise ValueError("the new order must contain exactly the pinned apps")
        self._write_pin_order(order)

    def _write_pin_order(self, order: list[str], also_pin: str | None = None) -> None:
        with self.db.transaction() as conn:
            if also_pin:
                conn.execute("UPDATE apps SET pinned = 1, hidden = 0 WHERE app_id = ?", (also_pin,))
            for i, app_id in enumerate(order):
                conn.execute("UPDATE apps SET pin_order = ? WHERE app_id = ?", (float(i), app_id))

    def remove_from_dock(self, app_id: str) -> None:
        """Unpin and hide from Recently Used. Launching it again brings it back."""
        with self.db.transaction() as conn:
            conn.execute("UPDATE apps SET pinned = 0, pin_order = NULL, hidden = 1 WHERE app_id = ?", (app_id,))
        self._write_pin_order([r.app_id for r in self.pinned()])

    def add_to_dock(self, rec: AppRecord) -> AppRecord:
        """User-added applications are pinned (so they stay) at the end of the pinned order."""
        self.ensure(rec)
        self.pin(rec.app_id)
        return self.get(rec.app_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------ meta
    def meta(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def forget(self, app_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM apps WHERE app_id = ?", (app_id,))
            conn.execute("DELETE FROM aliases WHERE app_id = ?", (app_id,))

    def with_updates(self, rec: AppRecord, **changes) -> AppRecord:
        return replace(rec, **changes)
