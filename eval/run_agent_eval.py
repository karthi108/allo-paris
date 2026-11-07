"""Rules vs hybrid (rules + AI agent) on route, messy and adversarial questions.

Uses the REAL configured LLM (ALLO_LLM_PROVIDER / ALLO_LLM_API_KEY in .env) with FIXED
fake transport data, so results are reproducible and use no PRIM quota. A disruption is
scripted on RER B so the eval checks the agent recommends a journey that avoids it.

Cost: about 22 questions x a few LLM calls (cents with small models). Not run in CI.

Usage:  python eval/run_agent_eval.py
Writes: eval/agent_results.json
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.agent import Agent  # noqa: E402
from app.agent.dialog import CallState, Dialog  # noqa: E402
from app.agent.llm import make_client  # noqa: E402
from app.agent.tools import Toolbox  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.prim import Departure, DeparturesResult, TrafficResult  # noqa: E402
from app.data.routes import Journey, Leg  # noqa: E402
from app.data.stops import StopArea, StopIndex  # noqa: E402

DISRUPTION_B = "Trafic interrompu entre Gare du Nord et Châtelet - Les Halles (incident technique)."


class EvalTransit:
    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult:
        now = datetime.now(UTC)
        deps = [
            Departure(line_id or "", d, now + timedelta(minutes=m, seconds=30), True)
            for m, d in ((3, "Terminus Nord"), (6, "Terminus Sud"), (11, "Terminus Nord"))
        ]
        return DeparturesResult(deps, now)

    def traffic(self, line_id: str) -> TrafficResult:
        return TrafficResult([DISRUPTION_B] if line_id == "C01743" else [], datetime.now(UTC))


class EvalPlanner:
    """Two journeys: the fastest uses RER B (disrupted), the other avoids it."""

    def __init__(self, index: StopIndex) -> None:
        self.index = index
        self.coords: dict[tuple[float, float], str] = {
            (a.lat, a.lon): a.name for a in index.areas if a.lat is not None and a.lon is not None
        }

    def plan(
        self,
        from_lat: float,
        from_lon: float,
        to_lat: float,
        to_lon: float,
        depart_at: datetime | None = None,
    ) -> list[Journey]:
        a = self.coords.get((from_lat, from_lon), "Origin")
        b = self.coords.get((to_lat, to_lon), "Destination")
        h = (depart_at or datetime.now()).strftime("%H")
        return [
            Journey(
                24,
                f"{h}:10",
                f"{h}:34",
                1,
                4,
                [
                    Leg(
                        "transit",
                        9,
                        "RapidTransit",
                        "B",
                        "Robinson",
                        a,
                        "Châtelet - Les Halles",
                        f"{h}:11",
                        f"{h}:20",
                    ),
                    Leg(
                        "transit",
                        12,
                        "Metro",
                        "1",
                        "La Défense",
                        "Châtelet",
                        b,
                        f"{h}:22",
                        f"{h}:34",
                    ),
                ],
            ),
            Journey(
                31,
                f"{h}:10",
                f"{h}:41",
                1,
                5,
                [
                    Leg(
                        "transit",
                        14,
                        "Metro",
                        "4",
                        "Bagneux",
                        a,
                        "Montparnasse Bienvenue",
                        f"{h}:12",
                        f"{h}:26",
                    ),
                    Leg(
                        "transit",
                        12,
                        "Metro",
                        "6",
                        "Charles de Gaulle - Étoile",
                        "Montparnasse Bienvenue",
                        b,
                        f"{h}:29",
                        f"{h}:41",
                    ),
                ],
            ),
        ]


def names_for(index: StopIndex, station_id: str) -> set[str]:
    area = index.by_id.get(str(station_id))
    return {s.name for s in index.siblings(area)} if area else set()


def judge(
    case: dict[str, Any], reply: Any, calls: list[tuple[str, dict[str, Any]]], index: StopIndex
) -> tuple[bool, str]:
    exp, text = case["expect"], reply.text
    routes = [args for name, args in calls if name == "plan_route"]
    if exp == "route":
        if reply.path == "rules" or reply.intent in ("unsupported_route", "unsupported_time"):
            return False, "no route computed"
        if not routes:
            return False, "plan_route not called"
        r = routes[-1]
        if case["to"] not in names_for(index, r.get("to_station_id", "")):
            return False, f"wrong destination {names_for(index, r.get('to_station_id', ''))}"
        if case["from"] not in names_for(index, r.get("from_station_id", "")):
            return False, f"wrong origin {names_for(index, r.get('from_station_id', ''))}"
        if case.get("depart_at") and not r.get("depart_at"):
            return False, "future time ignored"
        if case.get("avoid") and not re.search(r"\b(ligne|line|m[ée]tro|metro)\s?4\b", text, re.I):
            return False, "did not recommend the journey avoiding the disrupted RER B"
        return True, ""
    if exp == "ask_origin":
        if routes:
            return False, "guessed an origin"
        return (
            text.strip().endswith("?"),
            "" if text.strip().endswith("?") else "did not ask for the origin",
        )
    if exp == "departures":
        deps = [args for name, args in calls if name == "next_departures"]
        if reply.path == "rules":
            ok = (
                reply.intent == "next_departure"
                and reply.stop is not None
                and case["stop"] in names_for(index, reply.stop.zda_id)
                and reply.line is not None
                and reply.line.short == case["line"]
            )
            return ok, "" if ok else f"rules: {reply.intent}"
        if not deps:
            return False, "next_departures not called"
        d = deps[-1]
        area = index.by_id.get(str(d.get("station_id", "")))
        line_ok = area is not None and any(
            ln.line_id == d.get("line_id") and ln.short == case["line"]
            for ln in index.station_lines(area)
        )
        stop_ok = case["stop"] in names_for(index, d.get("station_id", ""))
        return (line_ok and stop_ok), "" if (line_ok and stop_ok) else f"wrong call {d}"
    if exp == "status":
        if reply.path == "rules":
            return reply.intent == "line_status", reply.intent
        ok = any(name == "line_status" for name, _ in calls)
        return ok, "" if ok else "line_status not called"
    if exp == "no_numbers":
        # Must not claim a time, a duration, a price or "free": examples like "ligne 4" are fine
        claim = re.search(r"\d+\s*(min|minute|€|eur|euro|h\b)|\b(free|gratuit)\b", text, re.I)
        return (claim is None), "" if claim is None else f"made a claim: {claim.group(0)!r}"
    return False, "unknown expectation"


def run_mode(mode: str, index: StopIndex, cases: list[dict[str, Any]]) -> dict[str, Any]:
    s = get_settings()
    transit, planner = EvalTransit(), EvalPlanner(index)
    boxes: list[Toolbox] = []

    def make_box() -> Toolbox:
        box = Toolbox(index, transit, None, planner)
        boxes.append(box)
        return box

    agent = None
    llm = None
    if mode == "hybrid":
        llm = make_client(
            s.llm_provider,
            s.llm_api_key,
            s.llm_model,
            daily_usd=max(s.llm_daily_budget_usd, 0.5),
            price_in=s.llm_price_in,
            price_out=s.llm_price_out,
        )
        if llm is None:
            sys.exit("Hybrid mode needs ALLO_LLM_PROVIDER and ALLO_LLM_API_KEY in .env")
        agent = Agent(llm, make_box)
    dialog = Dialog(index, transit, agent=agent)
    rows = []
    for case in cases:
        boxes.clear()
        reply = dialog.handle(case["q"], CallState(lang=case["lang"]))
        calls = [c for b in boxes for c in b.calls]
        ok, why = judge(case, reply, calls, index)
        rows.append(
            {
                "q": case["q"],
                "kind": case["kind"],
                "ok": ok,
                "why": why,
                "path": reply.path,
                "latency_ms": reply.latency_ms,
                "answer": reply.text,
            }
        )
        print(
            f"[{mode:6}] {'PASS' if ok else 'FAIL'} {reply.path:14} {reply.latency_ms:6d} ms  {case['q'][:60]}"
            + (f"  -> {why}" if why else "")
        )
    lat = [r["latency_ms"] for r in rows]
    by_kind: dict[str, list[bool]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["ok"])
    summary: dict[str, Any] = {
        "mode": mode,
        "questions": len(rows),
        "success_rate": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in by_kind.items()},
        "latency_p50_ms": round(statistics.median(lat)),
        "latency_p95_ms": sorted(lat)[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))],
        "ai_share": round(sum(r["path"].startswith("ai") for r in rows) / len(rows), 3),
        "guard_corrections": dialog.metrics.guard_retries,
        "guard_blocked_to_template": dialog.metrics.guard_fallbacks,
    }
    if llm is not None:
        summary["model"] = f"{llm.provider}/{llm.model}"
        summary["cost_usd_total"] = round(llm.budget.spent_usd, 4)
        summary["cost_usd_per_question"] = round(llm.budget.spent_usd / len(rows), 5)
    return {"summary": summary, "rows": rows}


def main() -> None:
    index = StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")
    cases = [
        json.loads(x)
        for x in (ROOT / "eval" / "questions_agent.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    results = {m: run_mode(m, index, cases) for m in ("rules", "hybrid")}
    print()
    for r in results.values():
        print(json.dumps(r["summary"], indent=2, ensure_ascii=False))
    out = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), **results}
    (ROOT / "eval" / "agent_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


_ = StopArea  # re-exported type used in annotations above

if __name__ == "__main__":
    main()
