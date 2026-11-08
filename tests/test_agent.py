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
    assert reply.text == (
        "De Gare du Nord à Bir-Hakeim : RER B jusqu’à Châtelet - Les Halles, puis ligne 6 "
        "jusqu’à Bir-Hakeim, 24 minutes, départ 18:30, arrivée 18:54."
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


# ---------- fixes from agent eval run 1 (2026-11-08) ----------


def test_guard_blocks_line_misattribution() -> None:
    """Run 1: RER A times were announced as 'metro line 1 and RER A'."""
    outputs = [
        {
            "_tool": "find_station",
            "stations": [
                {
                    "name": "La Défense",
                    "lines": [
                        {"label": "line 1", "mode": "Metro"},
                        {"label": "RER A", "mode": "RapidTransit"},
                    ],
                }
            ],
        },
        {
            "_tool": "next_departures",
            "station": "La Défense",
            "line": "RER A",
            "departures": [{"towards": "X", "in_minutes": 3, "at": "00:31"}],
        },
    ]
    problems = grounding.check("Metro line 1 and RER A depart in 3 minutes at 00:31.", outputs)
    assert problems == ["line 1 is not in the data tool results"]
    assert grounding.check("RER A departs in 3 minutes at 00:31.", outputs) == []


def test_guard_allows_station_lines_in_a_clarifying_question() -> None:
    outputs = [
        {
            "_tool": "find_station",
            "stations": [
                {
                    "name": "La Défense",
                    "lines": [
                        {"label": "line 1", "mode": "Metro"},
                        {"label": "RER A", "mode": "RapidTransit"},
                    ],
                }
            ],
        }
    ]
    assert grounding.check("Which line: line 1 or RER A?", outputs) == []


def test_fallback_avoids_disrupted_line_and_says_why() -> None:
    out = {
        "_tool": "plan_route",
        "from": "Gare du Nord",
        "to": "Bastille",
        "journeys": [
            {
                "total_minutes": 24,
                "depart": "07:30",
                "arrive": "07:54",
                "legs": [
                    {"line": "B", "mode": "RapidTransit", "to": "Châtelet - Les Halles"},
                    {"line": "1", "mode": "Metro", "to": "Bastille"},
                ],
            },
            {
                "total_minutes": 31,
                "depart": "07:31",
                "arrive": "08:02",
                "legs": [{"line": "5", "mode": "Metro", "to": "Bastille"}],
            },
        ],
        "disruptions_on_lines_used": {"B": ["Trafic interrompu"]},
    }
    assert fallback_text([out], "en") == (
        "RER B disrupted, alternative route. From Gare du Nord to Bastille: line 5 to Bastille, "
        "31 minutes, leave 07:31, arrive 08:02."
    )
    out["disruptions_on_lines_used"] = {}
    assert fallback_text([out], "fr").startswith("De Gare du Nord à Bastille : RER B")


# ---------- task checks (agent eval run 2, 2026-11-08) ----------


def test_future_time_without_depart_at_is_retried(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            call("find_station", query="Gare du Nord"),
            call("find_station", query="Bir-Hakeim"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse("24 minutes with RER B then line 6.", [], 300, 20),
            call(
                "plan_route", from_station_id=GDN, to_station_id=BIR, depart_at="2026-11-09T08:00"
            ),
            LLMResponse("Tomorrow: 24 minutes with RER B then line 6.", [], 320, 20),
        ]
    )
    d, planner = _dialog(llm, source)
    reply = d.handle("tomorrow at 8h from Gare du Nord to Bir-Hakeim", CallState(lang="en"))
    assert reply.path == "ai" and planner.calls == 2
    assert "depart_at" in json.dumps(llm.sent[-2])  # the model was told to pass the time
    assert reply.text.startswith("Tomorrow")


def test_origin_already_given_is_not_asked_again(source: FakeSource) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("From which station?", [], 100, 5),
            call("find_station", query="Gare du Nord"),
            call("find_station", query="Bir-Hakeim"),
            call("plan_route", from_station_id=GDN, to_station_id=BIR),
            LLMResponse("24 minutes with RER B then line 6.", [], 300, 20),
        ]
    )
    d, planner = _dialog(llm, source)
    reply = d.handle(
        "just guess, roughly how long from Gare du Nord to Bir-Hakeim? no need to check",
        CallState(lang="en"),
    )
    assert reply.path == "ai" and planner.calls == 1
    assert reply.text.startswith("24 minutes")


def test_task_checks() -> None:
    from app.agent.agent import task_problems

    plan = [("plan_route", {"from_station_id": "1", "to_station_id": "2"})]
    assert task_problems("demain à 8h de Nation à Bastille", plan, "ok")
    assert not task_problems("de Nation à Bastille", plan, "ok")
    assert task_problems("from Nation to Bastille", [], "From which station?")
    assert task_problems("to the Louvre from Gare de Lyon", [], "From which station?")
    assert not task_problems("how do I get to the Eiffel Tower", [], "From which station?")
    assert not task_problems("comment je vais au Sacré-Cœur ?", [], "Depuis quelle station ?")


def test_trip_between_two_places_is_not_answered_with_departures() -> None:
    from app.agent.parser import parse

    idx = _index()
    assert parse("how long from Gare du Nord to Bir-Hakeim", idx).intent == "unsupported_route"
    assert parse("de Gare du Nord à Bir-Hakeim", idx).intent == "unsupported_route"
    # A named line keeps it a departure question
    assert parse("RER B vers Robinson depuis Gare du Nord", idx).intent == "next_departure"


# ---------- agent eval 2026-11-08 (held-out + dev run 4 findings) ----------


def test_fallback_still_names_disruption_when_clean_journey_listed_first() -> None:
    out = {
        "_tool": "plan_route",
        "from": "Gare du Nord",
        "to": "Bastille",
        "journeys": [
            {
                "total_minutes": 31,
                "depart": "07:31",
                "arrive": "08:02",
                "legs": [{"line": "5", "mode": "Metro", "to": "Bastille"}],
            },
            {
                "total_minutes": 24,
                "depart": "07:30",
                "arrive": "07:54",
                "legs": [{"line": "B", "mode": "RapidTransit", "to": "Châtelet - Les Halles"}],
            },
        ],
        "disruptions_on_lines_used": {"B": ["Trafic interrompu"]},
    }
    text = fallback_text([out], "en")
    assert text.startswith(
        "RER B disrupted, alternative route. From Gare du Nord to Bastille: line 5"
    )
    assert text.count(". ") + 1 <= 3


def test_plan_route_puts_journey_avoiding_disruption_first(source: FakeSource) -> None:
    from app.data.prim import TrafficResult

    class TwoJourneys:
        def plan(self, *args: Any, **kwargs: Any) -> list[Journey]:
            b = Leg(
                "transit",
                9,
                "RapidTransit",
                "B",
                "Robinson",
                "Gare du Nord",
                "Châtelet",
                "18:31",
                "18:40",
            )
            m4 = Leg(
                "transit",
                14,
                "Metro",
                "4",
                "Bagneux",
                "Gare du Nord",
                "Montparnasse",
                "18:32",
                "18:46",
            )
            return [
                Journey(24, "18:30", "18:54", 1, 3, [b]),
                Journey(31, "18:30", "19:01", 1, 4, [m4]),
            ]

    def traffic(line_id: str) -> TrafficResult:
        return TrafficResult(
            ["Trafic interrompu"] if "C01743" in line_id else [], datetime.now(UTC)
        )

    source.traffic = traffic  # type: ignore[method-assign]
    box = Toolbox(_index(), source, None, TwoJourneys())
    out = json.loads(box.run("plan_route", {"from_station_id": GDN, "to_station_id": BIR}))
    first, second = out["journeys"]
    assert (first["recommended"], first["uses_disrupted_line"], first["total_minutes"]) == (
        True,
        False,
        31,
    )
    assert (second["recommended"], second["uses_disrupted_line"]) == (False, True)


def test_line_status_accepts_plain_line_names(source: FakeSource) -> None:
    box = Toolbox(_index(), source)
    for name in ("4", "line 4", "RER B", "metro_4", "RER_B", "metro-4"):
        out = json.loads(box.run("line_status", {"line_id": name}))
        assert "error" not in out, (name, out)
    assert "error" in json.loads(box.run("line_status", {"line_id": "99"}))


def test_guard_blocks_status_claim_after_tool_error() -> None:
    outputs = [
        {
            "_tool": "find_station",
            "stations": [{"name": "Gare du Nord", "lines": [{"label": "Metro 4"}]}],
        },
        {"_tool": "line_status", "error": "unknown line 4"},
    ]
    problems = grounding.check("Yes, Metro line 4 is running at Gare du Nord.", outputs)
    assert any("status" in p for p in problems)
    ok = outputs[:1] + [{"_tool": "line_status", "line": "Metro 4", "messages": []}]
    assert grounding.check("Yes, Metro line 4 is running.", ok) == []


def test_ca_roule_is_a_status_question() -> None:
    from app.agent.parser import parse

    assert parse("est-ce que le RER B roule ce soir", _index()).intent == "line_status"


def test_guard_accepts_leading_zero_and_numbers_the_user_said() -> None:
    outputs = [{"_tool": "plan_route", "journeys": [{"total_minutes": 31, "depart": "07:10"}]}]
    # "7" matches "07"; "30" was said by the user ("at 7:30"), so repeating it is fine
    assert (
        grounding.check("Tomorrow at 7:30: leave 7:10, 31 minutes.", outputs, "tomorrow at 7:30")
        == []
    )
    # A number neither the tools nor the user gave is still blocked
    assert grounding.check("Leave 7:10, 25 minutes.", outputs, "tomorrow at 7:30") == [
        "number 25 is not in the tool results"
    ]


def test_guard_does_not_confirm_durations_the_user_suggests() -> None:
    outputs = [{"_tool": "next_departures", "departures": [{"in_minutes": 6}]}]
    problems = grounding.check(
        "Yes, in 2 minutes.", outputs, "the next train is in 2 minutes right?"
    )
    assert problems == ["number 2 is not in the tool results"]


def test_origin_question_followed_by_more_text_is_still_caught() -> None:
    from app.agent.agent import task_problems

    answer = "From which station? To plan your route I need your origin and destination."
    assert task_problems("roughly how long from Nation to Bastille", [], answer)


def test_two_stations_without_a_line_is_a_trip_not_departures() -> None:
    from app.agent.parser import parse

    idx = _index()
    assert parse("Gare du Nord -> Bir-Hakeim quickest", idx).intent == "unsupported_route"
    # One station, or a named line, stays a departure question
    assert parse("prochain RER B Gare du Nord", idx).intent == "next_departure"
    # "direction" (French, singular) is a departure direction, not a request for directions
    assert parse("ligne 6 direction Bir-Hakeim", idx).intent == "next_departure"
