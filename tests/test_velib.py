from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.dialog import CallState, Dialog
from app.agent.parser import parse
from app.data.prim import FeedError
from app.data.stops import StopIndex, build_index_records
from app.data.velib import VelibClient, VelibResult, VelibStation, parse_records
from tests.conftest import FakeSource

# Shape of a real record from opendata.paris.fr, captured 2026-11-07
RECORD = {
    "stationcode": "10204",
    "name": "Dunkerque - Maubeuge",
    "is_installed": "OUI",
    "capacity": 35,
    "numdocksavailable": 26,
    "numbikesavailable": 9,
    "mechanical": 0,
    "ebike": 9,
    "is_renting": "OUI",
    "is_returning": "OUI",
    "duedate": "2026-11-07T18:50:28+00:00",
    "coordonnees_geo": {"lon": 2.3528900992907, "lat": 48.880432768947},
}


def test_parse_real_record() -> None:
    s = parse_records({"results": [RECORD]}, 48.8809, 2.3553)[0]
    assert (s.name, s.bikes, s.ebikes, s.docks, s.renting) == (
        "Dunkerque - Maubeuge",
        9,
        9,
        26,
        True,
    )
    assert 150 < s.distance_m < 250
    assert s.reported_at == datetime(2026, 11, 7, 18, 50, 28, tzinfo=UTC)


def test_bad_payload() -> None:
    with pytest.raises(FeedError):
        parse_records({"error": "x"}, 0, 0)


def test_budget_blocks_before_network() -> None:
    with pytest.raises(FeedError, match="budget"):
        VelibClient(daily_budget=0).nearby(48.88, 2.35)


class FakeBikes:
    def __init__(self, stations: list[VelibStation], age_min: int = 1, down: bool = False) -> None:
        self.stations, self.age_min, self.down = stations, age_min, down
        self.calls: list[tuple[float, float]] = []

    def nearby(self, lat: float, lon: float, radius_m: int = 500, limit: int = 3) -> VelibResult:
        self.calls.append((lat, lon))
        if self.down:
            raise FeedError("down")
        now = datetime.now(UTC)
        return VelibResult(
            [
                VelibStation(**{**s.__dict__, "reported_at": now - timedelta(minutes=self.age_min)})
                for s in self.stations
            ],
            now,
        )


def _idx() -> StopIndex:
    rows = [
        {
            "id": "IDFM:C01376",
            "shortname": "6",
            "mode": "Metro",
            "stop_id": "IDFM:1",
            "stop_name": "Bir-Hakeim",
            "stop_lat": "48.8539",
            "stop_lon": "2.2894",
        }
    ]
    return StopIndex.from_records(build_index_records(rows, [{"arrid": "1", "zdaid": "100"}]))


STATION = parse_records({"results": [RECORD]}, 48.8539, 2.2894)[0]


def test_velib_intent_and_answer(source: FakeSource) -> None:
    bikes = FakeBikes([STATION])
    reply = Dialog(_idx(), source, bikes=bikes).handle("Vélib à Bir-Hakeim", CallState())
    assert reply.intent == "velib"
    assert "9 vélos dont 9 électriques, 26 places libres" in reply.text
    assert bikes.calls == [(48.8539, 2.2894)] and not source.calls


def test_velib_landmark(source: FakeSource) -> None:
    reply = Dialog(_idx(), source, bikes=FakeBikes([STATION])).handle(
        "any bikes near the eiffel tower", CallState(lang="en")
    )
    assert reply.text.startswith("Nearest station to the Eiffel Tower: Bir-Hakeim. Vélib near")


def test_velib_old_report_is_flagged(source: FakeSource) -> None:
    reply = Dialog(_idx(), source, bikes=FakeBikes([STATION], age_min=90)).handle(
        "velib Bir-Hakeim", CallState()
    )
    assert "pas mis à jour depuis 90 minutes" in reply.text


def test_velib_down_gives_no_numbers(source: FakeSource) -> None:
    reply = Dialog(_idx(), source, bikes=FakeBikes([STATION], down=True)).handle(
        "velib Bir-Hakeim", CallState()
    )
    assert reply.intent == "feed_down" and "vélos" not in reply.text


def test_velib_without_place_asks(source: FakeSource) -> None:
    assert parse("il reste des vélos ?", _idx()).intent == "velib"
    reply = Dialog(_idx(), source, bikes=FakeBikes([STATION])).handle(
        "il reste des vélos ?", CallState()
    )
    assert reply.intent == "clarify_stop"
