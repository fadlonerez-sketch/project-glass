"""SQLite with versioned migrations. An unreadable database is renamed aside (never deleted) and recreated."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

log = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path, migrations: Sequence[str | Sequence[str]]):
        self.path = Path(path)
        self.migrations = migrations
        self.quarantined: Path | None = None
        self._lock = threading.RLock()
        self._open()

    def _open(self) -> None:
        try:
            self._migrate()
        except sqlite3.DatabaseError as exc:
            backup = self.path.with_name(f"{self.path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
            log.error("Database %s is unreadable (%s); moved to %s", self.path, exc, backup.name)
            self.path.replace(backup)
            self.quarantined = backup
            self._migrate()

    def _migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA quick_check").fetchone()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(self.migrations)):
                step = self.migrations[index]
                for statement in ([step] if isinstance(step, str) else step):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {index + 1}")
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
