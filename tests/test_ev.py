from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.data.prim import FeedError
from app.ev.belib import parse_export
from app.ev.history import EvHistory

# Shape of real export rows from opendata.paris.fr, captured 2026-11-08
ROW = {
    "adresse_station": "15 Av.Emile Deschanel 75007 Paris",
    "arrondissement": "07e Arrondissement",
    "coordonneesxy": {"lat": 48.855835, "lon": 2.3022223},
    "id_pdc": "FR*V75*EPX07*50*3*1",
    "last_updated": "2026-11-08T03:30:10+00:00",
    "statut_pdc": "Occupé (en charge)",
}
T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


def row(**kw: object) -> dict[str, object]:
    return {**ROW, **kw}


def test_parse_real_row() -> None:
    p = parse_export([ROW])[0]
    assert (p.point_id, p.status, p.raw_status) == (
        "FR*V75*EPX07*50*3*1",
        "charging",
        "Occupé (en charge)",
    )
    assert p.changed_at == datetime(2026, 11, 8, 3, 30, 10, tzinfo=UTC)
    assert p.station.startswith("15 Av.Emile") and p.lat == 48.855835


def test_parse_unknown_status_missing_geo_and_duplicates() -> None:
    pts = parse_export([row(statut_pdc="Nouveau statut", coordonneesxy=None), row(), {"no_id": 1}])
    assert len(pts) == 1 and pts[0].status == "other" and pts[0].lat is None


def test_parse_rejects_wrong_shape() -> None:
    with pytest.raises(FeedError):
        parse_export({"results": []})


def test_history_stores_only_changes_and_measures_last_updated() -> None:
    h = EvHistory(Path(":memory:"))
    s1 = h.record(parse_export([ROW]), T0)
    assert s1.new_events == 1 and s1.by_status == {"charging": 1}
    # Same status and time: nothing new
    s2 = h.record(parse_export([ROW]), T0 + timedelta(minutes=15))
    assert s2.new_events == 0
    # Same status, newer last_updated: a restamp (report time, not change time)
    s3 = h.record(
        parse_export([row(last_updated="2026-11-08T09:20:00+00:00")]), T0 + timedelta(minutes=30)
    )
    assert (s3.new_events, s3.restamped, s3.changed_same_time) == (1, 1, 0)
    # Status changed but last_updated did not move
    s4 = h.record(
        parse_export([row(last_updated="2026-11-08T09:20:00+00:00", statut_pdc="Disponible")]),
        T0 + timedelta(minutes=45),
    )
    assert (s4.new_events, s4.restamped, s4.changed_same_time) == (1, 0, 1)
    assert h.snapshot_count() == 4


def test_frozen_feed_is_marked_stale_not_stable() -> None:
    h = EvHistory(Path(":memory:"))
    assert not h.record(parse_export([ROW]), T0).stale
    # Same newest last_updated 3 minutes later: too soon to call it stale
    assert not h.record(parse_export([ROW]), T0 + timedelta(minutes=3)).stale
    # Still the same 22 minutes later: stale (the 2026-11-08 case)
    assert h.record(parse_export([ROW]), T0 + timedelta(minutes=22)).stale
    # The feed moves again: fresh
    fresh = parse_export([row(last_updated="2026-11-08T09:30:00+00:00")])
    assert not h.record(fresh, T0 + timedelta(minutes=30)).stale


def test_old_database_gets_stale_column() -> None:
    h = EvHistory(Path(":memory:"))
    h.db.execute("DROP TABLE snapshots")
    h.db.execute(
        "CREATE TABLE snapshots (observed_at TEXT PRIMARY KEY, points INTEGER NOT NULL, "
        "by_status TEXT NOT NULL, new_events INTEGER NOT NULL, restamped INTEGER NOT NULL, "
        "changed_same_time INTEGER NOT NULL, feed_newest TEXT)"
    )
    h._migrate()
    assert h.record(parse_export([ROW]), T0).stale is False


def test_snapshot_url_is_unique_and_keeps_all_rows() -> None:
    from app.ev.belib import snapshot_url

    a, b = snapshot_url(1), snapshot_url(2)
    assert a != b and "exports/json" in a
    assert "OR%201%20%3D%201" in a  # always true, so rows without last_updated stay


def test_csv_store_round_trip_across_runs() -> None:
    """Each scheduled run starts from the CSV files only, like a fresh CI runner."""
    import csv
    import tempfile

    from app.ev import csvstore

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        data = Path(d)
        s1 = csvstore.record(data, parse_export([ROW]), T0)
        assert s1.new_events == 1
        # Second run: same data 3 minutes later -> no new event, too soon to be stale
        s2 = csvstore.record(data, parse_export([ROW]), T0 + timedelta(minutes=3))
        assert s2.new_events == 0 and not s2.stale
        # Third run: still frozen 17 minutes after the previous one -> stale, but recorded
        s3 = csvstore.record(data, parse_export([ROW]), T0 + timedelta(minutes=20))
        assert s3.stale
        # Fourth run: status changed -> one event in today's file, state updated
        changed = parse_export(
            [row(statut_pdc="Disponible", last_updated="2026-11-08T09:25:00+00:00")]
        )
        s4 = csvstore.record(data, changed, T0 + timedelta(minutes=30))
        assert s4.new_events == 1 and not s4.stale
        with (data / "events" / "2026-11-08.csv").open(encoding="utf-8") as f:
            events = list(csv.DictReader(f))
        assert [e["status"] for e in events] == ["charging", "available"]
        with (data / "state.csv").open(encoding="utf-8") as f:
            assert [r["status"] for r in csv.DictReader(f)] == ["available"]
        with (data / "snapshots.csv").open(encoding="utf-8") as f:
            assert [r["stale"] for r in csv.DictReader(f)] == ["0", "0", "1", "0"]
        with (data / "points.csv").open(encoding="utf-8") as f:
            pts = list(csv.DictReader(f))
        assert len(pts) == 1 and pts[0]["first_seen"] == T0.isoformat(timespec="seconds")
