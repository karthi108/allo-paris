"""Phone test report (step 5): task completion, speech recognition errors, server latency.

The owner calls the Twilio number once per task in eval/phone_tasks.jsonl, in order, saying
the scripted sentences. This script reads the calls made since --since from the app's
SQLite database (turns: transcript, intent, answer, latency), pairs them with the tasks in
order, and reports:
- auto completion: an answer contains one of the task's expected words within max_turns
- owner completion: from eval/phone_verdicts.csv (task_id,completed,notes) if present;
  the owner's verdict is the one to quote (did the call do the job, by ear)
- word error rate of each transcript against the scripted sentence (speech recognition)
- turns per task and server latency p50 / p95 (dialog only: Twilio speech recognition
  and voice synthesis are not included, so the caller waits longer than this)

    python scripts/phone_report.py --db data/allo.db --since 2026-11-24T10:00 [--save]
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.stops import normalize  # noqa: E402


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate after accent and case folding (edit distance over words)."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def completed(task: dict[str, Any], answers: list[str]) -> bool:
    keys = [normalize(k) for k in task["must_any"]]
    return any(any(k in normalize(a) for k in keys) for a in answers[: task["max_turns"]])


def load_calls(db: Path, since: str) -> list[list[dict[str, Any]]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    calls = con.execute(
        "SELECT call_sid FROM calls WHERE started_at >= ? ORDER BY started_at", (since,)
    ).fetchall()
    out = []
    for c in calls:
        turns = con.execute(
            "SELECT transcript, intent, answer, latency_ms FROM turns WHERE call_sid = ? "
            "ORDER BY id",
            (c["call_sid"],),
        ).fetchall()
        out.append([dict(t) for t in turns])
    con.close()
    return out


def report(
    tasks: list[dict[str, Any]], calls: list[list[dict[str, Any]]], verdicts: dict[str, bool]
) -> dict[str, Any]:
    rows = []
    for task, turns in zip(tasks, calls, strict=False):
        answers = [t["answer"] for t in turns]
        wers = [wer(said, t["transcript"]) for said, t in zip(task["say"], turns, strict=False)]
        rows.append(
            {
                "id": task["id"],
                "goal": task["goal"],
                "turns": len(turns),
                "auto_completed": completed(task, answers),
                "owner_completed": verdicts.get(task["id"]),
                "wer": round(statistics.mean(wers), 3) if wers else None,
                "transcripts": [t["transcript"] for t in turns],
                "intents": [t["intent"] for t in turns],
                "latency_ms": [t["latency_ms"] for t in turns],
            }
        )
    lat = sorted(ms for r in rows for ms in r["latency_ms"])
    owner = [r["owner_completed"] for r in rows if r["owner_completed"] is not None]
    wers_all = [r["wer"] for r in rows if r["wer"] is not None]
    return {
        "tasks": len(tasks),
        "calls_found": len(calls),
        "auto_completion": f"{sum(r['auto_completed'] for r in rows)}/{len(rows)}",
        "owner_completion": f"{sum(owner)}/{len(owner)}" if owner else "not filled",
        "mean_wer": round(statistics.mean(wers_all), 3) if wers_all else None,
        "turns_per_task": round(statistics.mean(r["turns"] for r in rows), 2) if rows else None,
        "server_latency_p50_ms": lat[len(lat) // 2] if lat else None,
        "server_latency_p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "allo.db"))
    ap.add_argument("--since", required=True, help="UTC ISO time before the first test call")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    tasks = [
        json.loads(x)
        for x in (ROOT / "eval" / "phone_tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    verdicts: dict[str, bool] = {}
    sheet = ROOT / "eval" / "phone_verdicts.csv"
    if sheet.exists():
        with sheet.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                verdicts[r["task_id"]] = r["completed"].strip().lower() in ("yes", "oui", "1")
    rep = report(tasks, load_calls(Path(args.db), args.since), verdicts)
    if rep["calls_found"] != rep["tasks"]:
        print(f"warning: {rep['calls_found']} calls for {rep['tasks']} tasks (paired in order)")
    for r in rep["rows"]:
        print(
            f"{r['id']} auto={'yes' if r['auto_completed'] else 'no'} "
            f"owner={r['owner_completed']} turns={r['turns']} wer={r['wer']} | {r['goal']}"
        )
    summary = {k: v for k, v in rep.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False))
    if args.save:
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M")
        out = ROOT / "eval" / "results" / f"phone_{stamp}.json"
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
