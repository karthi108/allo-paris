"""Rules must hand over to the AI (or say "not understood") instead of answering a guess.

Causes found by held-out set 3 (2026-11-23). Wording here differs from every eval question.
Uses the full IDFM station snapshot that the rules eval also uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.agent.dialog import CallState, Dialog
from app.agent.parser import parse
from app.data.stops import StopIndex
from tests.conftest import FakeSource

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def full() -> StopIndex:
    return StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")


@pytest.mark.parametrize(
    "q", ["prochain départ à Springfield Plaza station", "next metro at Narnia Hall"]
)
def test_weak_station_guess_gets_no_departures(full: StopIndex, q: str) -> None:
    # Cause A: a station-like word in a fake name must not get real departure times
    reply = Dialog(full, FakeSource()).handle(q, CallState())
    assert reply.intent == "unknown"
    assert "minute" not in reply.text


@pytest.mark.parametrize(
    "q",
    [
        "Nation to the Eiffel Tower",
        "Opera vers Disneyland",
        "garre du nord jusqu'au Louvre",
        "Concorde to Orly",
    ],
)
def test_connector_trip_is_a_route(full: StopIndex, q: str) -> None:
    # Cause B: "X to Y" with a landmark or a misspelt station on one side
    assert parse(q, full).intent == "unsupported_route"


@pytest.mark.parametrize(
    "q",
    ["RER A vers La Défense à Nation", "prochain métro à Nation vers Château de Vincennes"],
)
def test_departure_with_direction_stays_departures(full: StopIndex, q: str) -> None:
    assert parse(q, full).intent == "next_departure"


@pytest.mark.parametrize("q", ["amène-moi au Sacré-Coeur", "bring me to the Arc de Triomphe"])
def test_landmark_destination_without_origin_is_a_route(full: StopIndex, q: str) -> None:
    # Cause C: a destination only; the AI asks where the trip starts
    assert parse(q, full).intent == "unsupported_route"


@pytest.mark.parametrize("q", ["Arc de Triomphe", "prochain métro Arc de Triomphe"])
def test_landmark_alone_or_with_departure_word_stays_departures(full: StopIndex, q: str) -> None:
    assert parse(q, full).intent == "next_departure"


@pytest.mark.parametrize("q", ["vélibs à République", "vellib Bastille", "velibe nation"])
def test_misspelt_velib_is_velib(full: StopIndex, q: str) -> None:
    # Cause D
    assert parse(q, full).intent == "velib"


def test_street_word_searches_the_address_first(full: StopIndex) -> None:
    # Cause E: "rue de Rome" is the street, not the station Rome
    sys.path.insert(0, str(ROOT / "eval"))
    from run_agent_eval import eval_chargers

    dialog = Dialog(full, FakeSource(), chargers=eval_chargers(full))
    street = dialog.handle("une borne libre rue de Rome ?", CallState())
    assert "15 Rue de Rome" in street.text
    # No street word: the station is used as before
    station = dialog.handle("borne près de Saint-Lazare", CallState())
    assert "15 Rue de Rome" in station.text


@pytest.mark.parametrize("q", ["is the 9 broken today", "what's up with the 13, any problems"])
def test_english_bare_line_number(full: StopIndex, q: str) -> None:
    # Cause F: "the 9" is line 9
    p = parse(q, full)
    assert p.intent == "line_status" and p.line is not None
    assert p.line.short in ("9", "13")


@pytest.mark.parametrize("q", ["Pigalle to the Sacré-Coeur?", "oberkampff jusqu'à Bercy"])
def test_agent_retries_when_origin_given_as_x_to_y(full: StopIndex, q: str) -> None:
    # Cause H: the AI asked for an origin given as "X to Y" (no from/de)
    from app.agent.agent import task_problems

    assert task_problems(q, [], "From which station?", full)


@pytest.mark.parametrize(
    "q", ["how do I get to the Arc de Triomphe", "je veux aller jusqu'à Bercy", "to the Louvre"]
)
def test_agent_does_not_retry_when_no_origin(full: StopIndex, q: str) -> None:
    from app.agent.agent import task_problems

    assert not task_problems(q, [], "From which station?", full)


def test_the_with_a_number_that_is_not_a_line(full: StopIndex) -> None:
    assert parse("is the 21 broken", full).line is None
