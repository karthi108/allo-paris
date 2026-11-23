"""Rules vs hybrid (rules + AI agent) on route, messy and adversarial questions.

Uses the REAL configured LLM (ALLO_LLM_PROVIDER / ALLO_LLM_API_KEY in .env) with FIXED
fake transport data, so results are reproducible and use no PRIM quota. A disruption is
scripted on RER B so the eval checks the agent recommends a journey that avoids it.

Cost: about 22 questions x a few LLM calls (cents with small models). Not run in CI.

Usage:  python eval/run_agent_eval.py                 (dev set: questions_agent.jsonl)
        python eval/run_agent_eval.py --set holdout   (held-out set, never tuned against)
        python eval/run_agent_eval.py --set holdout3  (held-out set 3, 92 questions, 2026-11-23)
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
from app.data.velib import VelibResult, VelibStation, _dist  # noqa: E402
from app.ev.belib import parse_export  # noqa: E402
from app.ev.live import ChargerClient  # noqa: E402
from app.rag.corpus import Corpus  # noqa: E402
from app.rag.retriever import Retriever, make_retriever  # noqa: E402

# RAG v1 corpus (real, committed snapshot): deterministic, so no fixture is needed (D-025)
DOCS = Corpus.load(ROOT / "data" / "docs.json")
RAG = "v2"  # --rag v1 = BM25 only in search_docs (RAG v1), for comparison
_CITE = re.compile(r"\(Source ?: ", re.I)
# "No document / not covered" wording, on normalize()d text (FR and EN)
_NO_DOC = re.compile(
    r"\b(pas de document|aucun document|no (official )?document|pas d information|"
    r"aucune information|no information|n ai pas (d information|de document)|"
    r"ne (couvre|couvrent) pas|pas couvert|not covered|do not cover|don t cover|"
    r"cannot answer|can t answer|ne peux pas (repondre|vous renseigner))\b"
)

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
    est_at = near("Gare de l'Est", 0.0006, -0.0004)
    ita_at = near("Place d'Italie", -0.0007, 0.0006)
    roquette = (48.8557, 2.3770)
    mtp_at = near("Gare Montparnasse", -0.0010, 0.0008)
    clovis = (48.8459, 2.3477)
    nat_at = near("Nation", 0.0005, 0.0009)
    laz_at = near("Saint-Lazare", -0.0006, -0.0007)
    cro_at = near("Château Rouge", 0.0007, 0.0004)
    hdv_at = near("Hôtel de Ville", -0.0006, 0.0006)
    rows = [
        row("R1", "8 Rue du Faubourg du Temple 75011 Paris", "Disponible", rep_at),
        row("R2", "8 Rue du Faubourg du Temple 75011 Paris", "Occupé (en charge)", rep_at),
        row("M1", "30 Boulevard de Vaugirard 75015 Paris", "Disponible", mtp_at),
        row("M2", "30 Boulevard de Vaugirard 75015 Paris", "Disponible", mtp_at),
        row("C1", "20 Rue Clovis 75005 Paris", "Inconnu", clovis),
        row("C2", "20 Rue Clovis 75005 Paris", "Inconnu", clovis),
        # Added for held-out set 2 (fixture places only; no code change)
        row("E1", "5 Rue d'Alsace 75010 Paris", "Disponible", est_at),
        row("I1", "100 Boulevard Vincent Auriol 75013 Paris", "Disponible", ita_at),
        row("I2", "100 Boulevard Vincent Auriol 75013 Paris", "En maintenance", ita_at),
        row("Q1", "40 Rue de la Roquette 75011 Paris", "En maintenance", roquette),
        row("Q2", "40 Rue de la Roquette 75011 Paris", "En maintenance", roquette),
        # Added for held-out set 3 (fixture places only, written before its first run)
        row("N1", "12 Avenue du Trône 75012 Paris", "Disponible", nat_at),
        row("N2", "12 Avenue du Trône 75012 Paris", "Disponible", nat_at),
        row("L1", "15 Rue de Rome 75008 Paris", "Occupé (en charge)", laz_at),
        row("L2", "15 Rue de Rome 75008 Paris", "Occupé (en charge)", laz_at),
        row("B1", "50 Boulevard Barbès 75018 Paris", "Inconnu", cro_at),
        row("H1", "2 Rue de Lobau 75004 Paris", "Disponible", hdv_at),
        row("H2", "2 Rue de Lobau 75004 Paris", "En maintenance", hdv_at),
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
        ]
        + [
            {
                "rule": "R1",
                "station": "40 Rue de la Roquette 75011 Paris",
                "detail": f"maintenance since Thu 05 Nov 10:40 UTC, {h} h observed",
            }
            for h in (74.0, 74.0)
        ]
        + [
            {
                "rule": "R4",
                "station": "50 Boulevard Barbès 75018 Paris",
                "detail": "no operator update for 9 days, 216 h observed",
            }
        ],
    }
    return ChargerClient(
        fetch=lambda: (parse_export(rows), datetime.now(UTC)), get_flags=lambda _: dict(flags)
    )


# Vélib'-shaped fixture for held-out set 3: invented station names placed near real stations
# (not real Vélib' data). (place, name, bikes, ebikes, free docks, open, dlat, dlon)
VELIB_FIXTURE: list[tuple[str, str, int, int, int, bool, float, float]] = [
    ("Odéon", "Odéon - Danton", 6, 2, 17, True, 0.0004, -0.0003),
    ("Trocadéro", "Trocadéro - Kléber", 0, 0, 0, False, 0.0006, 0.0005),
    ("Bastille", "Bastille - Richard Lenoir", 0, 0, 22, True, 0.0007, 0.0004),
    ("Gare de Lyon", "Gare de Lyon - Diderot", 14, 5, 9, True, -0.0005, 0.0006),
    ("Père Lachaise", "Père Lachaise - Gambetta", 3, 1, 18, True, 0.0004, 0.0005),
    ("Opéra", "Opéra - Auber", 11, 3, 4, True, 0.0003, -0.0006),
    ("Place de Clichy", "Clichy - Batignolles", 2, 0, 25, True, -0.0004, -0.0006),
]


class EvalBikes:
    """Fixed Vélib' stations; nearby() filters by real distance like the live client."""

    def __init__(self, index: StopIndex) -> None:
        self.stations: list[tuple[str, int, int, int, bool, float, float]] = []
        for place, name, bikes, ebikes, docks, open_, dlat, dlon in VELIB_FIXTURE:
            area = index.match(place, limit=1)[0].area
            lat, lon = (area.lat or 0) + dlat, (area.lon or 0) + dlon
            self.stations.append((name, bikes, ebikes, docks, open_, lat, lon))

    def nearby(self, lat: float, lon: float, radius_m: int = 500, limit: int = 3) -> VelibResult:
        now = datetime.now(UTC)
        found = []
        for name, bikes, ebikes, docks, open_, slat, slon in self.stations:
            d = _dist(lat, lon, slat, slon)
            if d <= radius_m:
                found.append(
                    VelibStation(
                        name,
                        name,
                        bikes,
                        ebikes,
                        bikes - ebikes,
                        docks,
                        open_,
                        open_,
                        now,
                        slat,
                        slon,
                        d,
                    )
                )
        found.sort(key=lambda s: s.distance_m)
        return VelibResult(found[:limit], now)


def fixture_streets(chargers: ChargerClient) -> set[str]:
    """Normalised street names of every fixture charger address (for 'ev_none')."""
    points, _ = chargers._points()  # noqa: SLF001 (eval reads its own fixture)
    return {
        normalize(re.sub(r"^\d+\s+|\s*\b75\d{3}\b.*$", "", p.station)) for p in points if p.station
    }


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
                # Ignore eval/: earlier runs rewrite its result files, which is not a code change
                ["git", "status", "--porcelain", "--untracked-files=no", "--", ".", ":!eval"],
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
        # Fixed 2026-11-23 after held-out set 3 run 1: a correct status from the rules path
        # (no tool call) used to fall through to the departures check and fail
        if reply.path == "rules" and reply.intent == "line_status":
            ok = reply.line is not None and reply.line.short == case["line"]
            return ok, "" if ok else "rules: status for the wrong line"
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
    # Added for held-out set 3, before its first run (see CHANGES.md)
    if exp == "velib":
        if normalize(case["station"]) not in normalize(text):
            return False, f"did not give the Vélib' station {case['station']!r}"
        if case.get("closed") and not re.search(r"ferm|closed", text, re.I):
            return False, "did not say the station is closed"
        n = case.get("number")
        if n == 0 and not re.search(
            r"\b0\b|aucun|pas de v[ée]lo|plus de v[ée]lo|\bno\b|\bnone\b|\bzero\b", text, re.I
        ):
            return False, "did not say there are no bikes"
        if n and not re.search(rf"\b{n}\b", text):
            return False, f"did not give the number {n}"
        return True, ""
    if exp == "velib_none":
        names = [normalize(v[1]) for v in VELIB_FIXTURE]
        if any(nm in normalize(text) for nm in names):
            return False, "named a Vélib' station that is not nearby"
        claim = re.search(r"\d+\s*(v[ée]los?|bikes?)", text, re.I)
        return (claim is None), "" if claim is None else f"made a claim: {claim.group(0)!r}"
    if exp == "ev_none":
        hit = [s for s in case["_streets"] if s and s in normalize(text)]
        return (not hit), "" if not hit else f"named a charger that is not nearby: {hit[0]}"
    # RAG v1 (D-025): document answers must cite source and date and give the expected fact
    if exp == "docs":
        if not _CITE.search(text) or "Service Public" not in text:
            return False, "no Service Public citation"
        text_n = normalize(text)
        if not any(normalize(k) in text_n for k in case["must_any"]):
            return False, f"none of {case['must_any']} in the answer"
        # Added 2026-11-23 after held-out set 4: the assistant states no prices or fees
        if case.get("no_price") and re.search(r"\d\s*(€|euros?)\b|€", text):
            return False, "stated a price or fee"
        return True, ""
    if exp == "access":
        if not _CITE.search(text) or "le-de-France Mobilit" not in text:
            return False, "no Île-de-France Mobilités citation"
        if normalize(case["level"]) not in normalize(text):
            return False, f"did not give the accessibility level {case['level']!r}"
        return True, ""
    if exp == "docs_none":
        # Added for held-out set 4, before its first run: a topic outside the corpus must get
        # "no document / not covered", never a cited or general-knowledge answer
        if _CITE.search(text):
            return False, "cited a source for a topic the corpus does not cover"
        ok = _NO_DOC.search(normalize(text)) is not None
        return ok, "" if ok else "did not say it has no document on this"
    if exp == "access_none":
        levels = ("non accessible", "sur demande", "sur reservation", "en toute autonomie")
        if any(lv in normalize(text) for lv in levels):
            return False, "gave an accessibility level for a station not in the data"
        ok = re.search(r"\b(RER|train)\b", text, re.I) is not None
        return ok, "" if ok else "did not say the data covers train and RER stations"
    if exp == "no_numbers":
        # Must not claim a time, a duration, a price or "free": examples like "ligne 4" are fine
        claim = re.search(r"\d+\s*(min|minute|€|eur|euro|h\b)|\b(free|gratuit)\b", text, re.I)
        return (claim is None), "" if claim is None else f"made a claim: {claim.group(0)!r}"
    return False, "unknown expectation"


def run_mode(
    mode: str,
    index: StopIndex,
    cases: list[dict[str, Any]],
    trace: bool = False,
    max_usd: float | None = None,
) -> dict[str, Any]:
    s = get_settings()
    transit, planner = EvalTransit(), EvalPlanner(index)
    chargers = eval_chargers(index)
    bikes = EvalBikes(index)
    streets = fixture_streets(chargers)
    boxes: list[Toolbox] = []
    retriever: Retriever | None = None

    def make_box() -> Toolbox:
        box = Toolbox(
            index, transit, bikes, planner, chargers=chargers, docs=DOCS, retriever=retriever
        )
        boxes.append(box)
        return box

    agent = None
    llm = None
    if mode == "hybrid":
        llm = make_client(
            s.llm_provider,
            s.llm_api_key,
            s.llm_model,
            # --max-usd is a hard cap for this run (CI); without it, the old default
            daily_usd=max_usd if max_usd is not None else max(s.llm_daily_budget_usd, 0.5),
            price_in=s.llm_price_in,
            price_out=s.llm_price_out,
        )
        if llm is None:
            sys.exit("Hybrid mode needs ALLO_LLM_PROVIDER and ALLO_LLM_API_KEY in .env")
        if RAG == "v2":
            retriever = make_retriever(DOCS, ROOT / "data" / "docs.json", llm)
        agent = Agent(llm, make_box)
    dialog = Dialog(index, transit, bikes=bikes, agent=agent, chargers=chargers, docs=DOCS)
    rows = []
    for case in cases:
        boxes.clear()
        reply = dialog.handle(case["q"], CallState(lang=case["lang"]))
        calls = [c for b in boxes for c in b.calls]
        outputs = [o for b in boxes for o in b.outputs]
        ok, why = judge({**case, "_streets": streets}, reply, calls, index)
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
                # What the tools were asked and returned, to diagnose failures from evidence
                "tool_trace": [
                    {
                        "call": name,
                        "args": args,
                        "output": json.dumps(out, ensure_ascii=False)[:600],
                    }
                    for (name, args), out in zip(calls, outputs, strict=False)
                ],
            }
        )
        print(
            f"[{mode:6}] {'PASS' if ok else 'FAIL'} {reply.path:14} {reply.latency_ms:6d} ms  {case['q'][:60]}"
            + (f"  -> {why}" if why else "")
        )
        if trace:
            for (name, args), out in zip(calls, outputs, strict=False):
                print(f"      tool {name}({json.dumps(args, ensure_ascii=False)})")
                print(f"        -> {json.dumps(out, ensure_ascii=False)[:400]}")
            print(f"      answer: {reply.text}")
            if reply.fallback:
                print(f"      fallback: {reply.fallback}")
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
        # The AI was skipped (cost cap reached, provider error): the run is not a measurement
        "ai_unavailable": sum(r["path"] == "rules_fallback" for r in rows),
    }
    if llm is not None:
        summary["model"] = f"{llm.provider}/{llm.model}"
        summary["cost_usd_total"] = round(llm.budget.spent_usd, 4)
        summary["cost_usd_per_question"] = round(llm.budget.spent_usd / len(rows), 5)
        summary["cost_cap_usd"] = llm.budget.daily_usd
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--set", choices=["dev", "holdout", "holdout2", "holdout3", "holdout4"], default="dev"
    )
    ap.add_argument("--only", help="run only questions containing this text (diagnosis, not saved)")
    ap.add_argument("--trace", action="store_true", help="print tool calls and outputs")
    ap.add_argument(
        "--max-usd", type=float, help="hard cost cap for this run (estimated from token usage)"
    )
    ap.add_argument("--summary", help="append a Markdown summary to this file (CI job summary)")
    ap.add_argument("--rag", choices=["v1", "v2"], default="v2", help="document search version")
    args = ap.parse_args()
    global RAG
    RAG = args.rag
    qfile = {
        "dev": "questions_agent.jsonl",
        "holdout": "questions_agent_holdout.jsonl",
        "holdout2": "questions_agent_holdout2.jsonl",
        "holdout3": "questions_agent_holdout3.jsonl",
        "holdout4": "questions_agent_holdout4.jsonl",
    }[args.set]
    index = StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")
    cases = [
        json.loads(x)
        for x in (ROOT / "eval" / qfile).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["q"].lower()]
        if not cases:
            sys.exit(f"no question contains {args.only!r}")
        run_mode("hybrid", index, cases, trace=True, max_usd=args.max_usd)
        print("\nDiagnosis run: nothing saved, not a measurement.")
        return
    results = {
        m: run_mode(m, index, cases, trace=args.trace, max_usd=args.max_usd)
        for m in ("rules", "hybrid")
    }
    print()
    for r in results.values():
        print(json.dumps(r["summary"], indent=2, ensure_ascii=False))
    skipped = results["hybrid"]["summary"]["ai_unavailable"]
    if skipped:
        msg = (
            f"AI unavailable on {skipped} question(s) (cost cap reached or provider error): "
            "not a measurement, nothing saved."
        )
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as f:
                f.write(f"## Agent eval ({args.set}): FAILED\n\n{msg}\n")
        sys.exit(msg)
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
    latest = "agent_results.json" if args.set == "dev" else f"agent_{args.set}_results.json"
    (ROOT / "eval" / latest).write_text(text, encoding="utf-8")
    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(exist_ok=True)
    prefix = "agent" if args.set == "dev" else f"agent_{args.set}"
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
    if args.summary:
        write_summary(args.summary, args.set, commit, results)


def write_summary(path: str, set_name: str, commit: str, results: dict[str, Any]) -> None:
    """Markdown for the CI job summary: scores, cost, and every failing answer to read."""
    h, r = results["hybrid"]["summary"], results["rules"]["summary"]
    n = h["questions"]
    lines = [
        f"## Agent eval ({set_name}, {commit}, {h.get('model', '')})",
        "",
        "| | Rules only | Hybrid |",
        "|---|---|---|",
        f"| Score (judge) | {round(r['success_rate'] * n)}/{n} | {round(h['success_rate'] * n)}/{n} |",
        f"| p50 / p95 | {r['latency_p50_ms']} / {r['latency_p95_ms']} ms "
        f"| {h['latency_p50_ms']} / {h['latency_p95_ms']} ms |",
        "",
        f"Cost ${h.get('cost_usd_total', 0)} (cap ${h.get('cost_cap_usd', '')}, estimated from "
        "token usage). Judge scores are not final until the answers are read.",
        "",
        "### Hybrid failures",
    ]
    fails = [x for x in results["hybrid"]["rows"] if not x["ok"]]
    for x in fails:
        answer = x["answer"].replace("|", "/").replace("\n", " ")[:200]
        lines.append(f"- **{x['q']}** ({x['path']}): {x['why']}. Answer: {answer}")
    if not fails:
        lines.append("- none")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


_ = StopArea  # re-exported type used in annotations above

if __name__ == "__main__":
    main()
