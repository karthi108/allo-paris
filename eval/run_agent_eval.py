"""Rules vs hybrid (rules + AI agent) on route, messy and adversarial questions.

Uses the REAL configured LLM (ALLO_LLM_PROVIDER / ALLO_LLM_API_KEY in .env) with FIXED
fake transport data, so results are reproducible and use no PRIM quota. A disruption is
scripted on RER B so the eval checks the agent recommends a journey that avoids it.

Cost: about 22 questions x a few LLM calls (cents with small models). Not run in CI.

Usage:  python eval/run_agent_eval.py                 (dev set: questions_agent.jsonl)
        python eval/run_agent_eval.py --set holdout   (held-out set, never tuned against)
Writes: eval/agent_results.json, eval/results/agent_<date>_<commit>.json, a row in eval/HISTORY.md
"""

from __future__ import annotations

import argparse
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
from app.data.stops import StopArea, StopIndex, normalize  # noqa: E402
from app.ev.belib import parse_export  # noqa: E402
from app.ev.live import ChargerClient  # noqa: E402

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


def eval_chargers(index: StopIndex) -> ChargerClient:
    """Fixed Belib'-shaped data placed next to real stations (fixture, not real chargers).
    The Rue Clovis points are out of service and flagged, to check warnings are passed on."""

    def near(name: str, dlat: float, dlon: float) -> tuple[float, float]:
        area = index.match(name, limit=1)[0].area
        return (area.lat or 0) + dlat, (area.lon or 0) + dlon

    def row(pid: str, address: str, status: str, at: tuple[float, float]) -> dict[str, Any]:
        return {
            "id_pdc": pid,
            "statut_pdc": status,
            "last_updated": datetime.now(UTC).isoformat(),
            "adresse_station": address,
            "arrondissement": "",
            "coordonneesxy": {"lat": at[0], "lon": at[1]},
        }

    rep_at = near("République", 0.0008, 0.0005)
    mtp_at = near("Gare Montparnasse", -0.0010, 0.0008)
    clovis = (48.8459, 2.3477)
    rows = [
        row("R1", "8 Rue du Faubourg du Temple 75011 Paris", "Disponible", rep_at),
        row("R2", "8 Rue du Faubourg du Temple 75011 Paris", "Occupé (en charge)", rep_at),
        row("M1", "30 Boulevard de Vaugirard 75015 Paris", "Disponible", mtp_at),
        row("M2", "30 Boulevard de Vaugirard 75015 Paris", "Disponible", mtp_at),
        row("C1", "20 Rue Clovis 75005 Paris", "Inconnu", clovis),
        row("C2", "20 Rue Clovis 75005 Paris", "Inconnu", clovis),
    ]
    flags = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "flags": [
            {
                "rule": "R1",
                "station": "20 Rue Clovis 75005 Paris",
                "detail": f"unknown since Mon 02 Nov 08:10 UTC, {h} h observed",
            }
            for h in (130.5, 130.5)
        ],
    }
    return ChargerClient(
        fetch=lambda: (parse_export(rows), datetime.now(UTC)), get_flags=lambda _: dict(flags)
    )


_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_WARNING = re.compile(
    r"fiab|unreliab|warning|attention|signal|flag|hors service|out of service", re.I
)


def quality(case: dict[str, Any], reply: Any) -> tuple[bool, str]:
    """Checks added after run 3 (2026-11-08) on every AI answer, both sets:
    - at most 3 sentences (answers are read aloud)
    - a route answer must not describe the disrupted journey (its 24-minute total)."""
    if not reply.path.startswith("ai"):
        return True, ""
    n = len(_SENTENCE_END.findall(reply.text.strip()))
    if n > 3:
        return False, f"{n} sentences (max 3 for voice)"
    if case.get("avoid") and re.search(r"\b24\s*min", reply.text):
        return False, "described the disrupted RER B journey"
    return True, ""


def git_state() -> tuple[str, bool]:
    import subprocess

    try:
        commit = subprocess.run(  # noqa: S603, S607 (fixed git command)
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(  # noqa: S603, S607
                ["git", "status", "--porcelain", "--untracked-files=no"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return commit, dirty


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
        targets = set(case.get("to_any") or [case["to"]])
        if not targets & names_for(index, r.get("to_station_id", "")):
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
    if exp == "departures_or_status":
        if any(name == "line_status" for name, _ in calls):
            line_ids = [str(a.get("line_id", "")) for n, a in calls if n == "line_status"]
            # The tool accepts ids or plain names ("4", "RER A") since 2026-11-08
            ok = any(
                ln.short == case["line"]
                for a in index.areas
                for ln in a.lines
                if ln.line_id in line_ids
            ) or any(
                re.sub(r"(?i)^(rer|line|ligne|m[ée]tro|m)\s*", "", x) == case["line"]
                for x in line_ids
            )
            return ok, "" if ok else f"status for wrong line {line_ids}"
        exp = "departures"
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
        if re.search(r"pas pu v[ée]rifier|couldn.t verify", text):
            return False, "generic fallback, no status given"
        ok = any(name == "line_status" for name, _ in calls)
        return ok, "" if ok else "line_status not called"
    if exp == "ev":
        text_n = normalize(text)
        if normalize(case["address"]) not in text_n:
            return False, f"did not give the charger address {case['address']!r}"
        if case.get("warn") and not _WARNING.search(text):
            return False, "did not pass on the reliability warning"
        return True, ""
    if exp == "no_numbers":
        # Must not claim a time, a duration, a price or "free": examples like "ligne 4" are fine
        claim = re.search(r"\d+\s*(min|minute|€|eur|euro|h\b)|\b(free|gratuit)\b", text, re.I)
        return (claim is None), "" if claim is None else f"made a claim: {claim.group(0)!r}"
    return False, "unknown expectation"


def run_mode(mode: str, index: StopIndex, cases: list[dict[str, Any]]) -> dict[str, Any]:
    s = get_settings()
    transit, planner = EvalTransit(), EvalPlanner(index)
    chargers = eval_chargers(index)
    boxes: list[Toolbox] = []

    def make_box() -> Toolbox:
        box = Toolbox(index, transit, None, planner, chargers=chargers)
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
    dialog = Dialog(index, transit, agent=agent, chargers=chargers)
    rows = []
    for case in cases:
        boxes.clear()
        reply = dialog.handle(case["q"], CallState(lang=case["lang"]))
        calls = [c for b in boxes for c in b.calls]
        ok, why = judge(case, reply, calls, index)
        if ok:
            ok, why = quality(case, reply)
        rows.append(
            {
                "q": case["q"],
                "kind": case["kind"],
                "ok": ok,
                "why": why,
                "path": reply.path,
                "latency_ms": reply.latency_ms,
                "fallback": reply.fallback,
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dev", "holdout"], default="dev")
    args = ap.parse_args()
    qfile = "questions_agent.jsonl" if args.set == "dev" else "questions_agent_holdout.jsonl"
    index = StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")
    cases = [
        json.loads(x)
        for x in (ROOT / "eval" / qfile).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    results = {m: run_mode(m, index, cases) for m in ("rules", "hybrid")}
    print()
    for r in results.values():
        print(json.dumps(r["summary"], indent=2, ensure_ascii=False))
    commit, dirty = git_state()
    now = datetime.now(UTC)
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "commit": commit,
        "dirty": dirty,
        "set": args.set,
        **results,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    latest = "agent_results.json" if args.set == "dev" else "agent_holdout_results.json"
    (ROOT / "eval" / latest).write_text(text, encoding="utf-8")
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(exist_ok=True)
    prefix = "agent" if args.set == "dev" else "agent_holdout"
    name = f"{prefix}_{now:%Y-%m-%d_%H%M}_{commit}{'-dirty' if dirty else ''}.json"
    (results_dir / name).write_text(text, encoding="utf-8")
    h, r = results["hybrid"]["summary"], results["rules"]["summary"]
    row = (
        f"| {now:%Y-%m-%d %H:%M} | {commit}{' (uncommitted changes)' if dirty else ''} "
        f"| {h.get('model', '')} | {r['success_rate']:.0%} | {h['success_rate']:.0%} "
        f"| {h['by_kind'].get('route', '')} | {h['latency_p50_ms']} / {h['latency_p95_ms']} ms "
        f"| ${h.get('cost_usd_per_question', 0)} "
        f"| {h['guard_corrections']} / {h['guard_blocked_to_template']} "
        f"| [{name}](results/{name}) |\n"
    )
    hist = ROOT / "eval" / ("HISTORY.md" if args.set == "dev" else "HOLDOUT.md")
    if not hist.exists():
        hist.write_text(
            "# Held-out agent eval\n\nQuestions in questions_agent_holdout.jsonl were written and "
            "committed before the first run. The code is never tuned against them: a failure "
            "here becomes a new dev-set question, never a fix aimed at this set.\n\n"
            "| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) "
            "| Cost / question | Guard | Results |\n|---|---|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    with hist.open("a", encoding="utf-8") as f:
        f.write(row)
    print(f"\nSaved eval/results/{name} and appended a row to eval/{hist.name}")


_ = StopArea  # re-exported type used in annotations above

if __name__ == "__main__":
    main()
