from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.agent.dialog import CallState, Dialog
from app.agent.parser import parse
from app.agent.tools import Toolbox
from app.data.prim import FeedError
from app.data.stops import StopIndex, build_index_records
from app.ev.belib import parse_export
from app.ev.live import ChargerClient, short_address
from tests.conftest import FakeSource

AT = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
PANTHEON = "17 Place du Panthéon 75005 Paris"
SOUFFLOT = "1 Rue Soufflot 75005 Paris"


def _row(pid: str, station: str, status: str, lat: float, lon: float) -> dict[str, Any]:
    return {
        "id_pdc": pid,
        "statut_pdc": status,
        "last_updated": "2026-11-08T11:50:00+00:00",
        "adresse_station": station,
        "arrondissement": "05e Arrondissement",
        "coordonneesxy": {"lat": lat, "lon": lon},
    }


ROWS = [
    _row("P1", PANTHEON, "Inconnu", 48.8462, 2.3464),
    _row("P2", PANTHEON, "Inconnu", 48.8462, 2.3464),
    _row("P3", PANTHEON, "Disponible", 48.8462, 2.3464),
    _row("S1", SOUFFLOT, "Disponible", 48.8466, 2.3440),
    _row("S2", SOUFFLOT, "Occupé (en charge)", 48.8466, 2.3440),
    _row("S3", SOUFFLOT, "Mise en service planifiée", 48.8466, 2.3440),
    _row("F1", "10 Avenue de la Porte 75019 Paris", "Disponible", 48.89, 2.40),  # far away
]
SILENT = "no update from the operator since 18 Jun 2026 (143 days), status unknown"
FLAGS = {
    "generated_at": "2026-11-08T11:53:00+00:00",
    "flags": [
        {"rule": "R4", "station": PANTHEON, "detail": SILENT},
        {"rule": "R4", "station": PANTHEON, "detail": SILENT},
    ],
}


def client(flags: Any = FLAGS) -> ChargerClient:
    def get_flags(_: str) -> dict[str, Any]:
        if isinstance(flags, Exception):
            raise flags
        return dict(flags)

    return ChargerClient(fetch=lambda: (parse_export(ROWS), AT), get_flags=get_flags)


def test_short_address_drops_postcode() -> None:
    assert short_address(PANTHEON) == "17 Place du Panthéon"


def test_nearby_groups_by_address_counts_and_flags() -> None:
    res = client().nearby(48.8462, 2.3464)
    assert [a.name for a in res.addresses] == ["17 Place du Panthéon", "1 Rue Soufflot"]
    p, s = res.addresses
    assert (p.in_service, p.available, p.out_of_service, len(p.flags)) == (3, 1, 2, 2)
    # "planned" points are not counted as in service
    assert (s.in_service, s.available, s.charging, s.flags) == (2, 1, 1, ())
    assert res.flags_as_of == datetime(2026, 11, 8, 11, 53, tzinfo=UTC)


def test_flags_unavailable_still_answers_live_status() -> None:
    res = client(flags=OSError("down")).nearby(48.8462, 2.3464)
    assert res.flags_as_of is None and len(res.addresses) == 2
    assert all(a.flags == () for a in res.addresses)


def test_find_address_uses_place_words_not_charger_words() -> None:
    found = client().find_address("y a une borne qui marche près du Panthéon ?")
    assert found is not None and found[2] == "17 Place du Panthéon"
    assert client().find_address("une borne près de chez moi") is None


def test_parser_sends_charger_questions_to_ev_not_status() -> None:
    idx = StopIndex.from_records(build_index_records([], []))
    assert parse("y a une borne qui marche près du Panthéon", idx).intent == "ev"
    assert parse("EV charger near Bastille", idx).intent == "ev"
    assert parse("prix de la recharge belib", idx).intent == "unsupported_price"


def test_rules_answer_by_address_with_reliability_warning(source: FakeSource) -> None:
    idx = StopIndex.from_records(build_index_records([], []))
    d = Dialog(idx, source, chargers=client())
    reply = d.handle("bornes près du Panthéon", CallState())
    assert reply.intent == "ev" and reply.path == "rules"
    assert reply.text.startswith("Bornes Belib' près de 17 Place du Panthéon.")
    assert "1 libre(s) sur 3, 2 hors service" in reply.text
    assert "2 borne(s) signalée(s) peu fiable(s)" in reply.text
    assert "1 Rue Soufflot" in reply.text and "Porte" not in reply.text


def test_rules_ev_feed_down(source: FakeSource) -> None:
    def broken() -> Any:
        raise FeedError("down")

    idx = StopIndex.from_records(build_index_records([], []))
    d = Dialog(idx, source, chargers=ChargerClient(fetch=broken, get_flags=lambda _: {}))
    reply = d.handle("bornes près du Panthéon", CallState())
    assert reply.intent == "feed_down" and "pas disponibles" in reply.text


def test_tool_by_place_returns_grounded_numbers(source: FakeSource) -> None:
    idx = StopIndex.from_records(build_index_records([], []))
    box = Toolbox(idx, source, chargers=client())
    out = json.loads(box.run("chargers_nearby", {"place": "Panthéon"}))
    assert out["near"] == "17 Place du Panthéon"
    first = out["addresses"][0]
    assert (first["free"], first["out_of_service"], len(first["reliability_warnings"])) == (1, 2, 2)
    err = json.loads(box.run("chargers_nearby", {}))
    assert "error" in err


@pytest.mark.parametrize("q", ["borne", "recharger ma voiture électrique"])
def test_ev_without_place_asks_where(q: str, source: FakeSource) -> None:
    idx = StopIndex.from_records(build_index_records([], []))
    d = Dialog(idx, source, chargers=client())
    reply = d.handle(q, CallState())
    assert reply.intent == "clarify_stop" and "quel endroit" in reply.text
