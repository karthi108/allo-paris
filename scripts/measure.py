"""Measure real end-to-end answer latency against LIVE IDFM PRIM data.

Cache disabled, so every question makes a real PRIM call (worst case, honest numbers).
Uses about 20 PRIM requests from your daily quota.

Usage:  python scripts/measure.py
Writes: eval/latency.json
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.dialog import CallState, Dialog  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.prim import PrimClient  # noqa: E402
from app.data.stops import StopIndex  # noqa: E402
from app.data.velib import VelibClient  # noqa: E402

QUESTIONS = [
    "prochain RER A à Châtelet",
    "ligne 4 Gare du Nord",
    "RER B Gare du Nord",
    "la 13 à Saint-Lazare",
    "le 14 à Gare de Lyon",
    "ligne 1 La Défense",
    "tram T2 La Défense",
    "ligne 6 Bir-Hakeim",
    "ligne 5 Bastille",
    "ligne 3 République",
    "RER C Invalides",
    "ligne 9 Trocadéro",
    "ligne 2 Pigalle",
    "RER D Gare de Lyon",
    "ligne 7 Place d'Italie",
    "perturbations RER B",
    "trafic ligne 13",
    "Vélib à Bastille",
    "Vélib à République",
    "near the eiffel tower line 6",
]


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def main() -> None:
    s = get_settings()
    if not s.prim_api_key:
        sys.exit("ALLO_PRIM_API_KEY missing in .env")
    prim = PrimClient(s.prim_api_key, cache_ttl=0, timeout=8)
    dialog = Dialog(StopIndex.load(s.stops_path), prim, bikes=VelibClient(cache_ttl=0, timeout=8))
    rows = []
    for q in QUESTIONS:
        t0 = time.perf_counter()
        reply = dialog.handle(q, CallState())
        ms = round((time.perf_counter() - t0) * 1000)
        rows.append({"q": q, "intent": reply.intent, "ms": ms, "answer": reply.text[:120]})
        print(f"{ms:5d} ms  [{reply.intent}]  {q}")
    answered = [r for r in rows if r["intent"] in ("next_departure", "line_status", "velib")]
    times = [float(r["ms"]) for r in answered]
    summary = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": len(rows),
        "answered_with_live_data": len(answered),
        "feed_errors": sum(r["intent"] == "feed_down" for r in rows),
        "p50_ms": round(statistics.median(times)) if times else None,
        "p95_ms": round(pct(times, 0.95)) if times else None,
        "max_ms": round(max(times)) if times else None,
        "prim_calls": prim.calls_made,
        "note": "server-side, cache off, home connection; excludes browser/phone network",
    }
    print(json.dumps(summary, indent=2))
    out = {"summary": summary, "rows": rows}
    (ROOT / "eval" / "latency.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
