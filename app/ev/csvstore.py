"""Plain-text storage of the charger history for the scheduled collector.

GitHub Actions runners start empty, so state lives in a git branch (ev-data) as CSV:
  points.csv      one row per charge point (no "last seen" column, so it rarely changes)
  state.csv       last known event per point, used to detect the next change
  snapshots.csv   one row per snapshot, including stale ones (gaps stay visible)
  events/YYYY-MM-DD.csv   status changes observed that day (UTC)
Text diffs keep the branch small; a SQLite file committed every 10 minutes would not.
Each run loads the CSVs into an in-memory EvHistory, records one snapshot, writes back.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from app.ev.belib import PointStatus
from app.ev.history import EvHistory, SnapshotSummary

POINT_COLS = ["point_id", "station", "arrondissement", "lat", "lon", "first_seen"]
EVENT_COLS = ["point_id", "status", "raw_status", "changed_at", "observed_at"]
SNAP_COLS = [
    "observed_at",
    "points",
    "by_status",
    "new_events",
    "restamped",
    "changed_same_time",
    "feed_newest",
    "stale",
]


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _none(v: str | None) -> str | None:
    return v if v else None


def load(data: Path) -> EvHistory:
    h = EvHistory(Path(":memory:"))
    with h.db:
        for r in _rows(data / "points.csv"):
            h.db.execute(
                "INSERT INTO points VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["point_id"],
                    r["station"],
                    r["arrondissement"],
                    float(r["lat"]) if r["lat"] else None,
                    float(r["lon"]) if r["lon"] else None,
                    r["first_seen"],
                    r["first_seen"],
                ),
            )
        for r in _rows(data / "state.csv"):
            h.db.execute(
                "INSERT INTO status_events VALUES (?, ?, ?, ?, ?)",
                (
                    r["point_id"],
                    r["status"],
                    r["raw_status"],
                    _none(r["changed_at"]),
                    r["observed_at"],
                ),
            )
        snaps = _rows(data / "snapshots.csv")
        if snaps:  # only the last one matters: stale detection compares with it
            s = snaps[-1]
            h.db.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s["observed_at"],
                    int(s["points"]),
                    s["by_status"],
                    int(s["new_events"]),
                    int(s["restamped"]),
                    int(s["changed_same_time"]),
                    _none(s["feed_newest"]),
                    int(s["stale"]),
                ),
            )
    return h


def _write(path: Path, cols: list[str], rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        w.writerows(rows)


def _append(path: Path, cols: list[str], rows: list[tuple[object, ...]]) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(cols)
        w.writerows(rows)


def save(h: EvHistory, data: Path, s: SnapshotSummary) -> None:
    now = s.observed_at.isoformat(timespec="seconds")
    points = h.db.execute(
        "SELECT point_id, station, arrondissement, lat, lon, first_seen FROM points "
        "ORDER BY point_id"
    ).fetchall()
    _write(
        data / "points.csv", POINT_COLS, [tuple("" if v is None else v for v in r) for r in points]
    )
    new_events = h.db.execute(
        "SELECT point_id, status, raw_status, changed_at, observed_at FROM status_events "
        "WHERE observed_at = ? ORDER BY point_id",
        (now,),
    ).fetchall()
    day = s.observed_at.strftime("%Y-%m-%d")
    _append(
        data / "events" / f"{day}.csv",
        EVENT_COLS,
        [tuple("" if v is None else v for v in r) for r in new_events],
    )
    state = h.db.execute(
        "SELECT point_id, status, raw_status, changed_at, observed_at FROM status_events e "
        "WHERE observed_at = (SELECT MAX(observed_at) FROM status_events "
        "WHERE point_id = e.point_id) ORDER BY point_id"
    ).fetchall()
    _write(
        data / "state.csv", EVENT_COLS, [tuple("" if v is None else v for v in r) for r in state]
    )
    _append(
        data / "snapshots.csv",
        SNAP_COLS,
        [
            (
                now,
                s.points,
                json.dumps(s.by_status, sort_keys=True),
                s.new_events,
                s.restamped,
                s.changed_same_time,
                s.feed_newest.isoformat(timespec="seconds") if s.feed_newest else "",
                int(s.stale),
            )
        ],
    )


def record(data: Path, points: list[PointStatus], observed_at: datetime) -> SnapshotSummary:
    h = load(data)
    s = h.record(points, observed_at)
    save(h, data, s)
    return s
