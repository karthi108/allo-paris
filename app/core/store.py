"""SQLite storage for call limits and short-lived logs (v1; Postgres later).

Stores only: HMAC caller ID, call SID, timestamps, transcript, intent, latency.
Never the raw phone number, never audio. Rows older than the retention period are
deleted on every write.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_sid TEXT PRIMARY KEY,
    caller_id TEXT NOT NULL,
    started_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_started ON calls(started_at);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT NOT NULL,
    at TEXT NOT NULL,
    transcript TEXT NOT NULL,
    intent TEXT NOT NULL,
    answer TEXT NOT NULL,
    latency_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_at ON turns(at);
"""


class Store:
    def __init__(self, path: Path, retention_days: int) -> None:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.retention = timedelta(days=retention_days)

    def _purge(self, now: datetime) -> None:
        cutoff = (now - self.retention).isoformat()
        self._db.execute("DELETE FROM turns WHERE at < ?", (cutoff,))
        self._db.execute("DELETE FROM calls WHERE started_at < ?", (cutoff,))

    def start_call(self, call_sid: str, caller_id: str, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        with self._lock, self._db:
            self._purge(now)
            self._db.execute(
                "INSERT OR IGNORE INTO calls VALUES (?, ?, ?)",
                (call_sid, caller_id, now.isoformat()),
            )

    def call_started_at(self, call_sid: str) -> datetime | None:
        row = self._db.execute(
            "SELECT started_at FROM calls WHERE call_sid = ?", (call_sid,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def counts_today(self, caller_id: str, now: datetime | None = None) -> tuple[int, int]:
        """Return (calls by this caller, calls overall) in the last 24 hours."""
        since = ((now or datetime.now(UTC)) - timedelta(days=1)).isoformat()
        total = self._db.execute(
            "SELECT COUNT(*) FROM calls WHERE started_at >= ?", (since,)
        ).fetchone()[0]
        mine = self._db.execute(
            "SELECT COUNT(*) FROM calls WHERE started_at >= ? AND caller_id = ?", (since, caller_id)
        ).fetchone()[0]
        return int(mine), int(total)

    def log_turn(
        self,
        call_sid: str,
        transcript: str,
        intent: str,
        answer: str,
        latency_ms: int,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        with self._lock, self._db:
            self._purge(now)
            self._db.execute(
                "INSERT INTO turns (call_sid, at, transcript, intent, answer, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (call_sid, now.isoformat(), transcript[:500], intent, answer[:1000], latency_ms),
            )

    def stats(self) -> dict[str, object]:
        calls = self._db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        rows = self._db.execute(
            "SELECT intent, COUNT(*), AVG(latency_ms) FROM turns GROUP BY intent"
        ).fetchall()
        lat = [r[0] for r in self._db.execute("SELECT latency_ms FROM turns ORDER BY latency_ms")]
        p50 = lat[len(lat) // 2] if lat else None
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None
        return {
            "calls": calls,
            "turns_by_intent": {r[0]: {"count": r[1], "avg_ms": round(r[2])} for r in rows},
            "latency_ms_p50": p50,
            "latency_ms_p95": p95,
        }
