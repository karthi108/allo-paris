from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.dialog import CallState, Dialog
from app.api.web import RateLimiter, WebApi
from app.data.prim import FeedError, PrimClient
from app.data.stops import StopIndex, build_index_records
from tests.conftest import FakeSource


def _api(index: StopIndex, source: FakeSource) -> WebApi:
    return WebApi(index, Dialog(index, source))


def test_departures_structured(index: StopIndex, source: FakeSource) -> None:
    d = _api(index, source).departures("42585", "C01374")
    assert d["stop"]["name"] == "Château Rouge"
    assert [x["destination"] for x in d["departures"]][:2] == [
        "Bagneux - Lucie Aubrac",
        "Porte de Clignancourt",
    ]
    assert d["departures"][0]["minutes"] == 2 and d["departures"][0]["realtime"] is True
    assert d["stale"] is False and "Bagneux" in d["answer"]


def test_departures_validation(index: StopIndex, source: FakeSource) -> None:
    api = _api(index, source)
    assert api.departures("nope", "C01374") == {"error": "unknown_stop"}
    assert api.departures("42585", "C01742") == {"error": "line_not_at_stop"}
    assert source.calls == []


def test_departures_feed_down_and_stale(index: StopIndex, source: FakeSource) -> None:
    api = _api(index, source)
    source.down = True
    assert api.departures("42585", "C01374")["error"] == "feed_down"
    source.down = False
    source.age = timedelta(seconds=600)
    d = api.departures("42585", "C01374")
    assert d["stale"] is True and d["departures"] == []


def test_ask_returns_stop_for_map(index: StopIndex, source: FakeSource) -> None:
    r = _api(index, source).ask("ligne 4 Château Rouge", "s1")
    assert r["intent"] == "next_departure"
    assert r["stop"]["id"] == "42585" and r["line"]["id"] == "C01374"


def test_ask_keeps_clarification_per_session(index: StopIndex, source: FakeSource) -> None:
    api = _api(index, source)
    assert api.ask("Châtelet", "a")["intent"] == "clarify_line"
    assert api.ask("ligne 4", "b")["intent"] != "next_departure"  # other session
    assert api.ask("ligne 4", "a")["intent"] == "next_departure"


def test_ask_truncates_and_handles_empty(index: StopIndex, source: FakeSource) -> None:
    api = _api(index, source)
    assert api.ask("   ", "s")["intent"] == "empty"
    api.ask("x" * 5000, "s")  # must not raise


def test_rate_limiter() -> None:
    rl = RateLimiter(per_minute=2)
    assert rl.allow("ip", now=0) and rl.allow("ip", now=1)
    assert not rl.allow("ip", now=2)
    assert rl.allow("other", now=2)
    assert rl.allow("ip", now=61)  # next window


def test_prim_budget_blocks_before_network() -> None:
    client = PrimClient("key", daily_budget=0)
    with pytest.raises(FeedError, match="budget"):
        client.next_departures("STIF:StopArea:SP:1:", None)
    assert client.calls_made == 0


def test_prim_without_key() -> None:
    with pytest.raises(FeedError, match="not configured"):
        PrimClient("").traffic("C01742")


def test_coords_and_colors_in_records() -> None:
    recs = build_index_records(
        [
            {
                "id": "IDFM:C01742",
                "shortname": "A",
                "mode": "RapidTransit",
                "stop_id": "IDFM:monomodalStopPlace:45102",
                "stop_name": "Châtelet - Les Halles",
                "stop_lat": "48.8617",
                "stop_lon": "2.3469",
            }
        ],
        [],
        {"C01742": ("eb2132", "ffffff")},
    )
    area = StopIndex.from_records(recs).by_id["45102"]
    assert area.lat == pytest.approx(48.8617) and area.lon == pytest.approx(2.3469)
    assert area.lines[0].color == "eb2132"


def test_stops_endpoint_skips_areas_without_coords(index: StopIndex, source: FakeSource) -> None:
    assert _api(index, source).stops() == []  # sample fixture has no coordinates
    _ = datetime.now(UTC)


def test_traffic_endpoint(index: StopIndex, source: FakeSource) -> None:
    api = _api(index, source)
    assert api.traffic("C99999") == {"error": "unknown_line"}
    assert api.traffic("C01743")["messages"] == []
    source.messages = ["Trafic perturbé"]
    assert api.traffic("C01743")["messages"] == ["Trafic perturbé"]
    source.down = True
    assert api.traffic("C01743")["error"] == "feed_down"


def _gare_du_nord_index() -> StopIndex:
    rows = [
        ("IDFM:C01374", "4", "Metro", "IDFM:463183", "Gare du Nord", "48.8797", "2.3567"),
        ("IDFM:C01375", "5", "Metro", "IDFM:463182", "Gare du Nord", "48.8797", "2.3567"),
        (
            "IDFM:C01743",
            "B",
            "RapidTransit",
            "IDFM:monomodalStopPlace:462394",
            "Gare du Nord",
            "48.8809",
            "2.3553",
        ),
        (
            "IDFM:C01728",
            "D",
            "RapidTransit",
            "IDFM:monomodalStopPlace:462394",
            "Gare du Nord",
            "48.8809",
            "2.3553",
        ),
    ]
    line_rows = [
        {
            "id": r[0],
            "shortname": r[1],
            "mode": r[2],
            "stop_id": r[3],
            "stop_name": r[4],
            "stop_lat": r[5],
            "stop_lon": r[6],
        }
        for r in rows
    ]
    return StopIndex.from_records(
        build_index_records(
            line_rows,
            [{"arrid": "463183", "zdaid": "462941"}, {"arrid": "463182", "zdaid": "462941"}],
        )
    )


def test_same_name_station_merged_on_map(source: FakeSource) -> None:
    idx = _gare_du_nord_index()
    stops = WebApi(idx, Dialog(idx, source)).stops()
    assert len(stops) == 1
    assert sorted(stops[0]["ids"]) == ["462394", "462941"]
    assert {ln["short"] for ln in stops[0]["lines"]} == {"4", "5", "B", "D"}


def test_departures_use_the_area_that_serves_the_line(source: FakeSource) -> None:
    idx = _gare_du_nord_index()
    api = WebApi(idx, Dialog(idx, source))
    metro_id = next(a.zda_id for a in idx.areas if any(ln.short == "4" for ln in a.lines))
    api.departures(metro_id, "C01743")  # RER B requested from the metro area id
    assert source.calls[-1] == ("STIF:StopArea:SP:462394:", "C01743")


def test_dialog_offers_all_lines_of_a_split_station(source: FakeSource) -> None:
    idx = _gare_du_nord_index()
    d, state = Dialog(idx, source), CallState()
    first = d.handle("Gare du Nord", state)
    assert first.intent == "clarify_line"
    assert "RER B" in first.text and "ligne 4" in first.text
    assert d.handle("RER D", state).intent == "next_departure"
    assert source.calls[-1] == ("STIF:StopArea:SP:462394:", "C01728")
