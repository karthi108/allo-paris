"""Status history of public charge points (SQLite). Public data only, no personal data.

Stores a status event only when a point's (status, changed_at) differs from its last
stored event, plus one row per snapshot so gaps in collection are visible (a gap is
missing data, never "the charger was fine").

Two counters test what the feed's last_updated means:
- restamped: same status, newer last_updated -> last_updated is (at least sometimes) a
  report time, not a change time.
- changed_same_time: different status, same last_updated -> last_updated is not updated
  on every change.
If both stay at 0 over days, "last_updated = last status change" is supported by data.

Stale snapshots: the feed's newest last_updated normally moves every few seconds. If it has
not moved for STALE_AFTER since the previous snapshot, the snapshot is marked stale (a
cached or frozen feed). Detection must ignore stale snapshots: "no change" from a frozen
feed is missing data, not a stable charger. Found on 2026-11-08 (22-minute-old copy).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.ev.belib import PointStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
    point_id TEXT PRIMARY KEY,
    station TEXT NOT NULL,
    arrondissement TEXT NOT NULL,
    lat REAL,
    lon REAL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status_events (
    point_id TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_status TEXT NOT NULL,
    changed_at TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_point ON status_events(point_id, observed_at);
CREATE TABLE IF NOT EXISTS snapshots (
    observed_at TEXT PRIMARY KEY,
    points INTEGER NOT NULL,
    by_status TEXT NOT NULL,
    new_events INTEGER NOT NULL,
    restamped INTEGER NOT NULL,
    changed_same_time INTEGER NOT NULL,
    feed_newest TEXT,
    stale INTEGER NOT NULL DEFAULT 0
);
"""
STALE_AFTER = timedelta(minutes=5)


@dataclass(frozen=True)
class SnapshotSummary:
    observed_at: datetime
    points: int
    by_status: dict[str, int]
    new_events: int
    restamped: int
    changed_same_time: int
    feed_newest: datetime | None
    stale: bool = False


class EvHistory:
    def __init__(self, path: Path) -> None:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(snapshots)")}
        if "stale" not in cols:  # databases created before the stale column existed
            self.db.execute("ALTER TABLE snapshots ADD COLUMN stale INTEGER NOT NULL DEFAULT 0")

    def _last(self) -> dict[str, tuple[str, str | None]]:
        rows = self.db.execute(
            "SELECT point_id, status, changed_at FROM status_events e "
            "WHERE observed_at = (SELECT MAX(observed_at) FROM status_events "
            "WHERE point_id = e.point_id)"
        ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def record(self, points: list[PointStatus], observed_at: datetime) -> SnapshotSummary:
        now = observed_at.isoformat(timespec="seconds")
        prev = self.db.execute(
            "SELECT observed_at, feed_newest FROM snapshots ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        last = self._last()
        by_status: dict[str, int] = {}
        new_events = restamped = changed_same_time = 0
        newest: datetime | None = None
        with self.db:
            for p in points:
                by_status[p.status] = by_status.get(p.status, 0) + 1
                if p.changed_at and (newest is None or p.changed_at > newest):
                    newest = p.changed_at
                changed = p.changed_at.isoformat(timespec="seconds") if p.changed_at else None
                self.db.execute(
                    "INSERT INTO points VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(point_id) "
                    "DO UPDATE SET last_seen = excluded.last_seen, station = excluded.station, "
                    "lat = excluded.lat, lon = excluded.lon",
                    (p.point_id, p.station, p.arrondissement, p.lat, p.lon, now, now),
                )
                before = last.get(p.point_id)
                if before == (p.status, changed):
                    continue
                if before is not None:
                    if before[0] == p.status:
                        restamped += 1
                    elif before[1] == changed:
                        changed_same_time += 1
                self.db.execute(
                    "INSERT INTO status_events VALUES (?, ?, ?, ?, ?)",
                    (p.point_id, p.status, p.raw_status, changed, now),
                )
                new_events += 1
            newest_s = newest.isoformat(timespec="seconds") if newest else None
            stale = bool(
                prev
                and prev[1] == newest_s
                and observed_at - datetime.fromisoformat(prev[0]) >= STALE_AFTER
            )
            self.db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now,
                    len(points),
                    json.dumps(by_status, sort_keys=True),
                    new_events,
                    restamped,
                    changed_same_time,
                    newest_s,
                    int(stale),
                ),
            )
        return SnapshotSummary(
            observed_at,
            len(points),
            by_status,
            new_events,
            restamped,
            changed_same_time,
            newest,
            stale,
        )

    def snapshot_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
