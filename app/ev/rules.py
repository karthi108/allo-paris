"""Reliability rules R1-R4 over the observed status history. Fixed code: no ML, no LLM.

R1 stuck: maintenance/unknown without a break for more than stuck_hours.
R2 ghost: "available" for more than ghost_hours with no session, while another point at
   the same address was used in that time (so quiet streets are not flagged).
R3 flapping: at least flap_changes status changes within one hour among available,
   unknown and maintenance (normal charging sessions are ignored), in the last 24 h.
R4 silent: the feed's last_updated for the point is older than silent_days.

Durations count only time covered by the collector: two good snapshots more than MAX_GAP
apart are a gap, and stale snapshots are ignored. A gap is never "stuck" and never "fine".
Points in "planned" (not yet in service) are never flagged.

Thresholds are PROVISIONAL until set from 7 days of real data (docs/decisions.md D-023).
Known limit: a status change is dated when the collector saw it (up to one interval late),
because the feed's last_updated is not a reliable change time (D-021).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

MAX_GAP = timedelta(minutes=30)
OUT_OF_SERVICE = {"maintenance", "unknown"}
NON_SESSION = {"available", "maintenance", "unknown"}


@dataclass(frozen=True)
class Thresholds:
    stuck_hours: float = 24.0  # R1, provisional
    ghost_hours: float = 72.0  # R2, provisional
    flap_changes: int = 6  # R3, changes per hour, provisional
    silent_days: float = 7.0  # R4, provisional


@dataclass(frozen=True)
class Event:
    status: str
    at: datetime  # when the collector observed it
    changed_at: datetime | None  # the feed's last_updated (supporting evidence only)


@dataclass
class Point:
    point_id: str
    station: str
    events: list[Event] = field(default_factory=list)

    def status_at(self, t: datetime) -> str | None:
        current = None
        for e in self.events:
            if e.at > t:
                break
            current = e.status
        return current


@dataclass(frozen=True)
class Flag:
    rule: str
    point_id: str
    station: str
    since: datetime
    covered_hours: float
    lower_bound: bool  # the state started before collection began: "at least"
    detail: str


class Coverage:
    def __init__(self, snapshots: list[tuple[datetime, bool]]) -> None:
        good = sorted(t for t, stale in snapshots if not stale)
        self.intervals = [(a, b) for a, b in zip(good, good[1:], strict=False) if b - a <= MAX_GAP]
        self.first = good[0] if good else None
        self.last = good[-1] if good else None
        self.gaps = sum(1 for a, b in zip(good, good[1:], strict=False) if b - a > MAX_GAP)
        self.stale = sum(1 for _, s in snapshots if s)

    def covered(self, start: datetime, end: datetime) -> timedelta:
        total = timedelta()
        for a, b in self.intervals:
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                total += hi - lo
        return total


def _hours(d: timedelta) -> float:
    return round(d.total_seconds() / 3600, 1)


def _trailing_run(events: list[Event], statuses: set[str]) -> list[Event]:
    run: list[Event] = []
    for e in reversed(events):
        if e.status not in statuses:
            break
        run.insert(0, e)
    return run


def r1_stuck(p: Point, cov: Coverage, th: Thresholds, now: datetime) -> Flag | None:
    run = _trailing_run(p.events, OUT_OF_SERVICE)
    if not run:
        return None
    since = run[0].at
    covered = cov.covered(since, now)
    if covered < timedelta(hours=th.stuck_hours):
        return None
    lower = run[0] is p.events[0]
    return Flag(
        "R1",
        p.point_id,
        p.station,
        since,
        _hours(covered),
        lower,
        f"{run[-1].status} since {since:%a %d %b %H:%M} UTC"
        + (" or earlier" if lower else "")
        + f", {_hours(covered)} h observed",
    )


def r2_ghost(
    p: Point, peers: list[Point], cov: Coverage, th: Thresholds, now: datetime
) -> Flag | None:
    if not p.events or p.events[-1].status != "available":
        return None
    since = p.events[-1].at
    covered = cov.covered(since, now)
    if covered < timedelta(hours=th.ghost_hours):
        return None
    used = [
        q
        for q in peers
        if q.status_at(since) == "charging"
        or any(e.status == "charging" and since <= e.at <= now for e in q.events)
    ]
    if not used:
        return None  # nobody charged at this address: a quiet place, not evidence of a fault
    lower = p.events[-1] is p.events[0]
    return Flag(
        "R2",
        p.point_id,
        p.station,
        since,
        _hours(covered),
        lower,
        f"available with no session for {_hours(covered)} h observed"
        + (" or more" if lower else "")
        + f", while {len(used)} other point(s) at this address were used",
    )


def r3_flapping(p: Point, cov: Coverage, th: Thresholds, now: datetime) -> Flag | None:
    start = now - timedelta(hours=24)
    changes = [
        b.at
        for a, b in zip(p.events, p.events[1:], strict=False)
        if b.at >= start
        and a.status != b.status
        and a.status in NON_SESSION
        and b.status in NON_SESSION
    ]
    best, best_at = 0, None
    for i, t in enumerate(changes):
        n = sum(1 for u in changes[i:] if u - t <= timedelta(hours=1))
        if n > best:
            best, best_at = n, t
    if best < th.flap_changes or best_at is None:
        return None
    return Flag(
        "R3",
        p.point_id,
        p.station,
        best_at,
        _hours(cov.covered(start, now)),
        False,
        f"{best} status changes within one hour from {best_at:%a %d %b %H:%M} UTC",
    )


def r4_silent(p: Point, th: Thresholds, now: datetime) -> Flag | None:
    if not p.events or p.events[-1].changed_at is None:
        return None
    changed = p.events[-1].changed_at
    if now - changed < timedelta(days=th.silent_days):
        return None
    return Flag(
        "R4",
        p.point_id,
        p.station,
        changed,
        0.0,
        False,
        f"no update from the operator since {changed:%d %b %Y} "
        f"({(now - changed).days} days), status {p.events[-1].status}",
    )


def evaluate(points: list[Point], cov: Coverage, th: Thresholds | None = None) -> list[Flag]:
    th = th or Thresholds()
    if cov.last is None:
        return []
    now = cov.last
    by_station: dict[str, list[Point]] = {}
    for p in points:
        by_station.setdefault(p.station, []).append(p)
    flags: list[Flag] = []
    for p in points:
        if not p.events or p.events[-1].status == "planned":
            continue
        peers = [q for q in by_station.get(p.station, []) if q is not p]
        for f in (
            r1_stuck(p, cov, th, now),
            r2_ghost(p, peers, cov, th, now),
            r3_flapping(p, cov, th, now),
            r4_silent(p, th, now),
        ):
            if f:
                flags.append(f)
    return flags


def _t(v: str) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def load_csv(data: Path) -> tuple[list[Point], Coverage]:
    """Read the ev-data branch layout written by app/ev/csvstore.py."""
    points: dict[str, Point] = {}
    with (data / "points.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            points[r["point_id"]] = Point(r["point_id"], r["station"])
    for path in sorted((data / "events").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                p = points.setdefault(r["point_id"], Point(r["point_id"], ""))
                at = _t(r["observed_at"])
                if at is not None:
                    p.events.append(Event(r["status"], at, _t(r["changed_at"])))
    for p in points.values():
        p.events.sort(key=lambda e: e.at)
    snaps: list[tuple[datetime, bool]] = []
    with (data / "snapshots.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            t = _t(r["observed_at"])
            if t is not None:
                snaps.append((t, r["stale"] == "1"))
    return list(points.values()), Coverage(snaps)
