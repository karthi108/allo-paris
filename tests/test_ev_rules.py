from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ev.rules import Coverage, Event, Point, Thresholds, evaluate

T0 = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)
TH = Thresholds(stuck_hours=24, ghost_hours=48, flap_changes=4, silent_days=7)


def snaps(hours: float, every_min: int = 10, skip: tuple[float, float] | None = None) -> Coverage:
    out = []
    t = T0
    while t <= T0 + timedelta(hours=hours):
        h = (t - T0).total_seconds() / 3600
        if not (skip and skip[0] <= h < skip[1]):
            out.append((t, False))
        t += timedelta(minutes=every_min)
    return Coverage(out)


def ev(status: str, hours: float, changed_days_ago: float | None = None) -> Event:
    at = T0 + timedelta(hours=hours)
    changed = at - timedelta(days=changed_days_ago) if changed_days_ago is not None else at
    return Event(status, at, changed)


def rules(points: list[Point], cov: Coverage) -> set[tuple[str, str]]:
    return {(f.rule, f.point_id) for f in evaluate(points, cov, TH)}


def test_coverage_excludes_gaps() -> None:
    cov = snaps(30, skip=(10, 20))
    assert cov.gaps == 1
    covered = cov.covered(T0, T0 + timedelta(hours=30)).total_seconds() / 3600
    assert 19.5 < covered < 20.5


def test_r1_stuck_needs_observed_time_not_wall_clock() -> None:
    p = Point("p1", "A", [ev("available", 0), ev("unknown", 1)])
    assert ("R1", "p1") in rules([p], snaps(30))
    # Same 29 h on the clock, but a 10 h gap: only 19 h observed -> not flagged
    assert ("R1", "p1") not in rules([p], snaps(30, skip=(10, 20)))


def test_r1_counts_unknown_then_maintenance_as_one_outage_and_marks_lower_bound() -> None:
    p = Point("p1", "A", [ev("unknown", 0), ev("maintenance", 5)])
    flags = [f for f in evaluate([p], snaps(30), TH) if f.rule == "R1"]
    assert len(flags) == 1 and flags[0].lower_bound and "or earlier" in flags[0].detail


def test_r1_not_flagged_once_back_in_service() -> None:
    p = Point("p1", "A", [ev("unknown", 0), ev("available", 28)])
    assert ("R1", "p1") not in rules([p], snaps(30))


def test_r2_ghost_only_when_a_neighbour_was_used() -> None:
    ghost = Point("g", "A", [ev("charging", 0), ev("available", 1)])
    used = Point("u", "A", [ev("available", 0), ev("charging", 20), ev("available", 22)])
    assert ("R2", "g") in rules([ghost, used], snaps(60))
    # Nobody charged at address B during the window: quiet street, not evidence of a fault
    quiet = Point("q", "B", [ev("available", 0)])
    idle = Point("i", "B", [ev("available", 0)])
    flagged = rules([quiet, idle], snaps(60))
    assert ("R2", "q") not in flagged and ("R2", "i") not in flagged


def test_r3_flapping_ignores_normal_sessions() -> None:
    flappy = Point(
        "f",
        "A",
        [
            ev(s, 10 + i * 0.1)
            for i, s in enumerate(["available", "unknown", "available", "unknown", "available"])
        ],
    )
    sessions = Point(
        "s",
        "A",
        [
            ev(s, 10 + i * 0.1)
            for i, s in enumerate(["available", "charging", "available", "charging", "available"])
        ],
    )
    flagged = rules([flappy, sessions], snaps(20))
    assert ("R3", "f") in flagged and ("R3", "s") not in flagged


def test_r4_silent_and_planned_points_are_never_flagged() -> None:
    silent = Point("s", "A", [ev("available", 0, changed_days_ago=150)])
    planned = Point("p", "A", [ev("planned", 0, changed_days_ago=150)])
    flagged = rules([silent, planned], snaps(2))
    assert ("R4", "s") in flagged
    assert not any(pid == "p" for _, pid in flagged)


def test_no_good_snapshots_means_no_flags() -> None:
    p = Point("p1", "A", [ev("unknown", 0)])
    assert evaluate([p], Coverage([(T0, True)]), TH) == []
