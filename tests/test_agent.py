"""AI layer tests with a scripted fake LLM: no network, no cost."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.agent import grounding
from app.agent.agent import Agent, fallback_text
from app.agent.dialog import CallState, Dialog
from app.agent.llm import (
    AnthropicClient,
    Budget,
    LLMClient,
    LLMResponse,
    LLMUnavailable,
    OpenAIClient,
    ToolCall,
    ToolSpec,
    make_client,
)
from app.agent.tools import Toolbox
from app.data.routes import Journey, Leg, parse_journeys
from app.data.stops import StopIndex, build_index_records
from tests.conftest import FakeSource

# ---------- index with coordinates: Gare du Nord (4, B) and Bir-Hakeim (6) ----------


def _index() -> StopIndex:
    rows = [
        ("IDFM:C01374", "4", "Metro", "IDFM:463183", "Gare du Nord", "48.8797", "2.3567"),
        (
            "IDFM:C01743",
            "B",
            "RapidTransit",
            "IDFM:monomodalStopPlace:462394",
            "Gare du Nord",
            "48.8809",
            "2.3553",
        ),
        ("IDFM:C01376", "6", "Metro", "IDFM:22000", "Bir-Hakeim", "48.8539", "2.2894"),
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
    arr = [{"arrid": "463183", "zdaid": "462941"}, {"arrid": "22000", "zdaid": "100"}]
    return StopIndex.from_records(build_index_records(line_rows, arr))


class FakePlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan(
        self,
        from_lat: float,
        from_lon: float,
        to_lat: float,
        to_lon: float,
        depart_at: datetime | None = None,
    ) -> list[Journey]:
        self.calls += 1
        return [
            Journey(
                24,
                "18:30",
                "18:54",
                1,
                6,
                [
                    Leg(
                        "transit",
                        9,
                        "RapidTransit",
                        "B",
                        "Robinson",
                        "Gare du Nord",
                        "Châtelet - Les Halles",
                        "18:31",
                        "18:40",
                    ),
                    Leg(
                        "transit",
                        11,
                        "Metro",
                        "6",
                        "Nation",
                        "Charles de Gaulle - Étoile",
                        "Bir-Hakeim",
                        "18:42",
                        "18:53",
                    ),
                ],
            ),
        ]


class ScriptedLLM(LLMClient):
    """Returns pre-written responses in order; records what it was sent."""

    provider = "fake"

    def __init__(self, script: list[LLMResponse]) -> None:
        super().__init__("key", "fake", Budget(1.0, 1.0, 1.0))
        self.script = list(script)
        self.sent: list[list[dict[str, Any]]] = []

    def _chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> LLMResponse:
        self.sent.append(json.loads(json.dumps(messages)))
        return self.script.pop(0)

    def assistant_turn(self, resp: LLMResponse) -> dict[str, Any]:
        return {"role": "assistant", "content": resp.text or "[tools]"}

    def tool_results_turn(self, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [{"role": "user", "content": out} for _, out in results]


def _dialog(llm: LLMClient | None, source: FakeSource) -> tuple[Dialog, FakePlanner]:
    idx = _index()
    planner = FakePlanner()
    agent = Agent(llm, lambda: Toolbox(idx, source, None, planner)) if llm else None
    return Dialog(idx, source, agent=agent), planner


def call(name: str, **args: Any) -> LLMResponse:
    return LLMResponse("", [ToolCall(f"c{name}", name, args)], 100, 20)


GDN, BIR = "462941", "100"

# ---------- grounding guard ----------


def test_guard_accepts_numbers_and_lines_from_tools() -> None:
    outputs = [
        {
            "journeys": [
                {
                    "total_minutes": 24,
                    "legs": [{"line": "B", "mode": "RapidTransit"}, {"line": "6", "mode": "Metro"}],
                }
            ]
        }
    ]
    assert grounding.check("Take RER B then line 6: 24 minutes.", outputs) == []


def test_guard_blocks_invented_number_and_line() -> None:
    outputs = [
        {"journeys": [{"total_minutes": 24, "legs": [{"line": "B", "mode": "RapidTransit"}]}]}
    ]
    problems = grounding.check("Take RER A then line 9: 20 minutes.", outputs)
    assert "number 20 is not in the tool results" in problems
    assert any("line A" in p for p in problems) and any("line 9" in p for p in problems)


# ---------- agent loop ----------


def test_route_question_goes_to_ai_and_is_grounded(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            call("find_station", query="Gare du Nord"),
            call("find_station", query="tour Eiffel"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse(
                "From Gare du Nord take RER B to Châtelet - Les Halles, then line 6 to Bir-Hakeim: 24 minutes, arriving 18:54.",
                [],
                300,
                40,
            ),
        ]
    )
    d, planner = _dialog(llm, source)
    reply = d.handle(
        "I want to go to the Eiffel Tower from Gare du Nord, fastest route?", CallState(lang="en")
    )
    assert reply.path == "ai" and reply.intent == "ai"
    assert "24 minutes" in reply.text and planner.calls == 1
    assert reply.tools == ["find_station", "find_station", "plan_route"]


def test_invented_value_triggers_retry_then_passes(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            call("find_station", query="Gare du Nord"),
            call("find_station", query="Bir-Hakeim"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse("About 20 minutes with RER B and line 6.", [], 300, 20),
            LLMResponse("24 minutes with RER B then line 6.", [], 320, 20),
        ]
    )
    d, _ = _dialog(llm, source)
    reply = d.handle("comment aller de Gare du Nord à Bir-Hakeim", CallState())
    assert reply.path == "ai" and reply.text.startswith("24 minutes")
    assert "invented" not in reply.text and d.metrics.guard_retries == 1
    assert "number 20" in json.dumps(llm.sent[-1])  # the model was told what was wrong


def test_repeated_invention_falls_back_to_template(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            call("find_station", query="Gare du Nord"),
            call("find_station", query="Bir-Hakeim"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse("RER A, 15 minutes.", [], 300, 10),
            LLMResponse("RER A, 15 minutes!", [], 300, 10),
        ]
    )
    d, _ = _dialog(llm, source)
    reply = d.handle("comment aller de Gare du Nord à Bir-Hakeim", CallState())
    assert reply.path == "ai_fallback"
    assert (
        reply.text
        == "De Gare du Nord à Bir-Hakeim : RER B jusqu’à Châtelet - Les Halles, puis ligne 6 jusqu’à Bir-Hakeim. Durée 24 minutes."
    )
    assert d.metrics.guard_fallbacks == 1


def test_ai_asks_origin_and_followup_goes_back_to_ai(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            call("find_station", query="tour Eiffel"),
            LLMResponse("From which station?", [], 100, 5),
            call("find_station", query="Gare du Nord"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse("RER B then line 6: 24 minutes.", [], 300, 10),
        ]
    )
    d, _ = _dialog(llm, source)
    state = CallState(lang="en")
    first = d.handle("how do I get to the Eiffel Tower", state)
    assert first.text == "From which station?" and state.ai_followup
    second = d.handle("Gare du Nord", state)  # rules alone would ask "which line?"
    assert second.path == "ai" and "24 minutes" in second.text
    assert len(state.history) == 4


def test_rules_still_answer_simple_questions_without_ai_cost(source: FakeSource) -> None:
    llm = ScriptedLLM([])  # any call would fail: the script is empty
    d, _ = _dialog(llm, source)
    reply = d.handle("ligne 4 Gare du Nord", CallState())
    assert reply.path == "rules" and reply.intent == "next_departure"
    assert llm.sent == []


def test_ai_unavailable_falls_back_to_rules(source: FakeSource) -> None:
    class DownLLM(ScriptedLLM):
        def _chat(self, *a: Any) -> LLMResponse:
            raise LLMUnavailable("HTTP 429")

    d, _ = _dialog(DownLLM([]), source)
    reply = d.handle("comment aller de Gare du Nord à Bir-Hakeim", CallState())
    assert reply.path == "rules_fallback" and reply.intent == "unsupported_route"


def test_no_llm_configured_behaves_like_before(source: FakeSource) -> None:
    d, _ = _dialog(None, source)
    assert d.handle("comment aller à Nation", CallState()).path == "rules"


def test_budget_cap_blocks_calls() -> None:
    b = Budget(daily_usd=0.001, price_in=1000.0, price_out=1000.0)
    b.record(10, 10)
    with pytest.raises(LLMUnavailable, match="budget"):
        b.check()


def test_tool_errors_are_returned_not_raised(source: FakeSource) -> None:
    box = Toolbox(_index(), source)
    out = json.loads(box.run("next_departures", {"station_id": "nope", "line_id": "x"}))
    assert "unknown station_id" in out["error"]
    out = json.loads(box.run("plan_route", {"from_station_id": GDN, "to_station_id": BIR}))
    assert "not available" in out["error"]
    assert json.loads(box.run("drop_database", {}))["error"].startswith("unknown tool")


def test_find_station_landmark_and_split_station(source: FakeSource) -> None:
    out = json.loads(Toolbox(_index(), source).run("find_station", {"query": "effile tower"}))
    assert out["stations"][0]["name"] == "Bir-Hakeim"
    out = json.loads(Toolbox(_index(), source).run("find_station", {"query": "gare du nord"}))
    assert {ln["label"] for ln in out["stations"][0]["lines"]} == {"line 4", "RER B"}


def test_departures_tool_shape(source: FakeSource) -> None:
    out = json.loads(
        Toolbox(_index(), source).run("next_departures", {"station_id": GDN, "line_id": "C01374"})
    )
    assert out["departures"][0]["in_minutes"] == 2 and out["line"] == "line 4"


# ---------- provider adapters (wire format) ----------


def test_anthropic_wire_format() -> None:
    seen: dict[str, Any] = {}

    def post(
        url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        seen.update(url=url, headers=headers, body=body)
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "find_station",
                    "input": {"query": "Nation"},
                }
            ],
            "usage": {"input_tokens": 50, "output_tokens": 7},
        }

    c = make_client("anthropic", "sk-test", post=post)
    assert isinstance(c, AnthropicClient)
    r = c.chat(
        "sys",
        [{"role": "user", "content": "hi"}],
        [ToolSpec("find_station", "d", {"type": "object"})],
    )
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["body"]["tools"][0][
        "input_schema"
    ] == {"type": "object"}
    assert r.tool_calls[0].args == {"query": "Nation"} and r.input_tokens == 50
    turn = c.tool_results_turn([(r.tool_calls[0], "{}")])
    assert turn[0]["content"][0]["type"] == "tool_result"


def test_openai_wire_format() -> None:
    def post(
        url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        assert headers["authorization"] == "Bearer sk-o" and body["messages"][0]["role"] == "system"
        return {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "x",
                                "type": "function",
                                "function": {
                                    "name": "line_status",
                                    "arguments": '{"line_id": "C01743"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        }

    c = make_client("openai", "sk-o", post=post)
    assert isinstance(c, OpenAIClient)
    r = c.chat("sys", [], [])
    assert r.tool_calls[0].name == "line_status" and r.tool_calls[0].args == {"line_id": "C01743"}
    assert c.tool_results_turn([(r.tool_calls[0], "{}")])[0]["role"] == "tool"


def test_make_client_without_key_is_none() -> None:
    assert make_client("anthropic", "") is None and make_client("nope", "k") is None


# ---------- route parsing (Navitia format) ----------


NAVITIA = {
    "journeys": [
        {
            "duration": 1500,
            "nb_transfers": 1,
            "type": "best",
            "departure_date_time": "20261107T183000",
            "arrival_date_time": "20261107T185500",
            "sections": [
                {"type": "street_network", "mode": "walking", "duration": 120},
                {
                    "type": "public_transport",
                    "duration": 540,
                    "departure_date_time": "20261107T183200",
                    "arrival_date_time": "20261107T184100",
                    "display_informations": {
                        "commercial_mode": "RER",
                        "code": "B",
                        "direction": "Robinson",
                    },
                    "from": {"name": "Gare du Nord"},
                    "to": {"name": "Châtelet les Halles"},
                },
                {"type": "transfer", "duration": 180},
                {"type": "waiting", "duration": 60},
                {
                    "type": "public_transport",
                    "duration": 660,
                    "display_informations": {
                        "commercial_mode": "Métro",
                        "code": "6",
                        "direction": "Nation",
                    },
                    "from": {"name": "Charles de Gaulle Étoile"},
                    "to": {"name": "Bir-Hakeim"},
                },
            ],
        },
        {
            "duration": 2400,
            "sections": [{"type": "street_network", "mode": "walking", "duration": 2400}],
        },
    ]
}


def test_parse_journeys() -> None:
    js = parse_journeys(NAVITIA)
    assert len(js) == 1  # walking-only journey dropped
    j = js[0]
    assert (j.minutes, j.depart, j.arrive, j.transfers, j.walk_minutes) == (
        25,
        "18:30",
        "18:55",
        1,
        5,
    )
    transit = [leg for leg in j.legs if leg.kind == "transit"]
    assert [(leg.mode, leg.line) for leg in transit] == [("RapidTransit", "B"), ("Metro", "6")]
    assert transit[0].depart == "18:32"


def test_parse_journeys_no_solution() -> None:
    assert parse_journeys({"error": {"id": "no_solution"}}) == []


def test_fallback_text_departures() -> None:
    out = [
        {
            "station": "Nation",
            "line": "line 1",
            "departures": [{"towards": "La Défense", "in_minutes": 3}],
        }
    ]
    assert fallback_text(out, "en") == "line 1 at Nation: towards La Défense in 3 minutes."
    _ = datetime.now(UTC) - timedelta(seconds=1)
