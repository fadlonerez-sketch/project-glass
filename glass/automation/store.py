"""automation.db: client tokens (hashes only), scopes, the deny list, the stop flag and the audit log."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from glass.core import security

ALL_SCOPES = ["inspect", "act", "text", "windows", "input"]
DEFAULT_SCOPES = {"owner": ALL_SCOPES, "garvis": list(ALL_SCOPES)}
DEFAULT_DENY_LIST = [
    "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "dashlane.exe", "lastpass.exe",
    "enpass.exe", "nordpass.exe", "credentialuibroker.exe", "consent.exe", "logonui.exe",
    "sechealthui.exe", "securityhealthsystray.exe",
]
AUDIT_KEEP = 20000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (name TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
                                    scopes TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL, client TEXT,
                                  method TEXT, target TEXT, outcome TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_time ON audit(time);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = self._open()
        except sqlite3.DatabaseError:
            path.rename(path.with_suffix(f".corrupt-{int(time.time())}"))
            self._conn = self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA user_version=1")
        return conn

    # ------------------------------------------------------------------ clients and tokens
    def ensure_client_tokens(self) -> None:
        """Create owner/garvis tokens on first start, and rotate any whose secret file is missing or
        no longer matches (the plain token is only ever stored DPAPI-protected for its client)."""
        for name in ("owner", "garvis"):
            row = self._one("SELECT token_hash, scopes FROM clients WHERE name=?", (name,))
            existing = security.read_secret(name)
            if row and existing and security.token_matches(existing, row[0]):
                continue
            token = security.new_token()
            security.write_secret(name, token)
            scopes = json.loads(row[1]) if row else DEFAULT_SCOPES[name]
            with self._lock:
                self._conn.execute("INSERT OR REPLACE INTO clients VALUES (?,?,?,?)",
                                   (name, security.token_hash(token), json.dumps(scopes), time.time()))

    def authenticate(self, token: str) -> tuple[str, list[str]] | None:
        if not token:
            return None
        h = security.token_hash(token)
        row = self._one("SELECT name, scopes FROM clients WHERE token_hash=?", (h,))
        if not row:
            return None
        return row[0], json.loads(row[1])

    def scopes(self, client: str) -> list[str]:
        row = self._one("SELECT scopes FROM clients WHERE name=?", (client,))
        return json.loads(row[0]) if row else []

    def set_scopes(self, client: str, scopes: list[str]) -> list[str]:
        clean = [s for s in ALL_SCOPES if s in set(scopes)]
        if client == "owner":
            clean = list(ALL_SCOPES)
        with self._lock:
            cur = self._conn.execute("UPDATE clients SET scopes=? WHERE name=?", (json.dumps(clean), client))
        if cur.rowcount == 0:
            raise KeyError(client)
        return clean

    def clients(self) -> dict[str, list[str]]:
        with self._lock:
            rows = self._conn.execute("SELECT name, scopes FROM clients ORDER BY name").fetchall()
        return {n: json.loads(s) for n, s in rows}

    # ------------------------------------------------------------------ deny list, stop flag
    def _kv(self, key: str, default):
        row = self._one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row[0]) if row else default

    def _set_kv(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))

    def deny_list(self) -> list[str]:
        return self._kv("deny_list", list(DEFAULT_DENY_LIST))

    def set_deny_list(self, items: list[str]) -> list[str]:
        clean = sorted({i.strip().lower() for i in items if i and i.strip()})
        self._set_kv("deny_list", clean)
        return clean

    def stopped(self) -> bool:
        return bool(self._kv("stopped", False))

    def set_stopped(self, value: bool) -> None:
        self._set_kv("stopped", bool(value))

    # ------------------------------------------------------------------ audit
    def audit(self, client: str, method: str, target: str, outcome: str, detail: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit (time, client, method, target, outcome, detail) VALUES (?,?,?,?,?,?)",
                (time.time(), client, method, target[:500], outcome, detail[:2000]))
            new_id = cur.lastrowid
            if new_id % 500 == 0:
                self._conn.execute("DELETE FROM audit WHERE id <= ?", (new_id - AUDIT_KEEP,))
        return new_id

    def read_audit(self, limit: int = 200, since_id: int | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 2000))
        with self._lock:
            if since_id is not None:
                rows = self._conn.execute(
                    "SELECT id,time,client,method,target,outcome,detail FROM audit WHERE id>? ORDER BY id ASC LIMIT ?",
                    (int(since_id), limit)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id,time,client,method,target,outcome,detail FROM audit ORDER BY id DESC LIMIT ?",
                    (limit,)).fetchall()
        keys = ("id", "time", "client", "method", "target", "outcome", "detail")
        return [dict(zip(keys, r)) for r in rows]

    def _one(self, sql: str, args: tuple):
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
