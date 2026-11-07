"""Offline evaluation of question understanding on the real IDFM station list.

Uses eval/data/stops_snapshot.json (IDFM open data snapshot, 2026-11-07) and a fixed
fake data source, so results are reproducible and need no network or API key.

Metrics:
- intent accuracy: did we classify the question correctly?
- line accuracy / station accuracy: on questions where a line / station is expected
- invented numbers: any number in an answer that comes neither from the data source nor
  from a fixed template, station or line name (target: 0)

Usage:  python eval/run_eval.py            (prints a table, writes eval/results.json)
        python eval/run_eval.py --check    (exit 1 if below thresholds; used in CI)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.dialog import CallState, Dialog, T  # noqa: E402
from app.agent.parser import parse  # noqa: E402
from app.data.prim import Departure, DeparturesResult, TrafficResult  # noqa: E402
from app.data.stops import StopIndex  # noqa: E402
from app.data.velib import VelibResult, VelibStation  # noqa: E402

THRESHOLDS = {"intent_accuracy": 0.95, "line_accuracy": 0.95, "stop_accuracy": 0.95}
SOURCE_MINUTES = (2, 5, 9, 14)
VELIB_NUMBERS = (7, 3, 12, 180)
NUM = re.compile(r"\d+")


class EvalSource:
    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult:
        now = datetime.now(UTC)
        deps = [
            Departure(line_id or "", dest, now + timedelta(minutes=m, seconds=30), True)
            for m, dest in zip(SOURCE_MINUTES, ("Nord", "Sud", "Nord", "Sud"), strict=True)
        ]
        return DeparturesResult(deps, now)

    def traffic(self, line_id: str) -> TrafficResult:
        return TrafficResult([], datetime.now(UTC))


class EvalBikes:
    def nearby(self, lat: float, lon: float, radius_m: int = 500, limit: int = 3) -> VelibResult:
        bikes, ebikes, docks, dist = VELIB_NUMBERS
        st = VelibStation(
            "1",
            "Station Vélib",
            bikes,
            ebikes,
            bikes - ebikes,
            docks,
            True,
            True,
            datetime.now(UTC),
            lat,
            lon,
            dist,
        )
        return VelibResult([st], datetime.now(UTC))


@dataclass
class Row:
    q: str
    expected: dict[str, str | None]
    got: dict[str, str | None]
    answer: str
    invented: list[str]

    @property
    def ok(self) -> bool:
        e, g = self.expected, self.got
        return (
            e["intent"] == g["intent"]
            and (e["line"] is None or e["line"] == g["line"])
            and (e["stop"] is None or e["stop"] == g["stop"])
            and not self.invented
        )


def _allowed_numbers(lang: str, *texts: str) -> set[str]:
    allowed = {str(m) for m in SOURCE_MINUTES} | {str(n) for n in VELIB_NUMBERS}
    allowed |= {str(m + 1) for m in SOURCE_MINUTES}  # rounding at minute boundaries
    allowed |= {str(s) for s in range(6)}  # "updated N seconds ago": data age, measured
    allowed |= set(NUM.findall(" ".join(T[lang].values())))
    for text in texts:
        allowed |= set(NUM.findall(text))
    return allowed


def run() -> tuple[dict[str, float | int], list[Row]]:
    index = StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")
    dialog = Dialog(index, EvalSource(), bikes=EvalBikes())
    rows: list[Row] = []
    for raw in (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        case = json.loads(raw)
        reply = dialog.handle(case["q"], CallState(lang=case["lang"]))
        parsed = parse(case["q"], index)
        line = reply.line or parsed.line
        stop = reply.stop or (parsed.stops[0].area if parsed.stops else None)
        names = [stop.name if stop else "", line.short if line else ""]
        if stop:  # lines offered back to the caller come from the station's own data
            names += [ln.short for ln in index.station_lines(stop)]
        names += [a.name for a in index.areas if a.name in reply.text]
        allowed = _allowed_numbers(case["lang"], *names)
        invented = [n for n in NUM.findall(reply.text) if n not in allowed]
        rows.append(
            Row(
                case["q"],
                {k: case[k] for k in ("intent", "line", "stop")},
                {
                    "intent": reply.intent,
                    "line": line.short if line else None,
                    "stop": stop.name if stop else None,
                },
                reply.text,
                invented,
            )
        )

    def acc(key: str) -> float:
        rel = [r for r in rows if r.expected[key] is not None or key == "intent"]
        good = [r for r in rel if r.expected[key] == r.got[key]]
        return round(len(good) / len(rel), 3) if rel else 1.0

    metrics: dict[str, float | int] = {
        "questions": len(rows),
        "intent_accuracy": acc("intent"),
        "line_accuracy": acc("line"),
        "stop_accuracy": acc("stop"),
        "fully_correct": round(sum(r.ok for r in rows) / len(rows), 3),
        "invented_numbers": sum(len(r.invented) for r in rows),
    }
    return metrics, rows


def main() -> None:
    metrics, rows = run()
    for r in rows:
        if not r.ok:
            print(f"FAIL {r.q!r}\n     expected {r.expected}\n     got      {r.got}")
            if r.invented:
                print(f"     invented numbers {r.invented} in: {r.answer}")
    print(json.dumps(metrics, indent=2))
    out = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "metrics": metrics}
    (ROOT / "eval" / "results.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if "--check" in sys.argv:
        failed = [k for k, v in THRESHOLDS.items() if float(metrics[k]) < v]
        if failed or metrics["invented_numbers"]:
            print(f"Below threshold: {failed}, invented={metrics['invented_numbers']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
