from datetime import UTC, datetime, timedelta

from app.agent.validator import numbers_grounded
from app.data.schema import Freshness, Source


def test_grounded_numbers_pass() -> None:
    payload = '{"line": "RER A", "minutes": [3, 11]}'
    assert numbers_grounded("RER A in 3 and 11 minutes", payload)


def test_invented_number_fails() -> None:
    payload = '{"line": "RER A", "minutes": [3, 11]}'
    assert not numbers_grounded("RER A in 4 minutes", payload)


def test_stale_realtime_detected() -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    f = Freshness(
        source=Source.PRIM_NEXT_DEPARTURES, fetched_at=now - timedelta(seconds=300), realtime=True
    )
    assert f.is_stale(now, stale_after_seconds=120)


def test_scheduled_data_never_stale() -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    f = Freshness(source=Source.IDFM_GTFS, fetched_at=now - timedelta(days=2), realtime=False)
    assert not f.is_stale(now, stale_after_seconds=120)
