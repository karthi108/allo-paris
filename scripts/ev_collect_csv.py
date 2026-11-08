"""Scheduled collector (GitHub Actions): one Belib' snapshot into CSV files.

Usage:  python scripts/ev_collect_csv.py --data evdata
Exit codes: 0 ok · 1 fetch failed (nothing written) · 2 stale feed (snapshot written, flagged)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.prim import FeedError  # noqa: E402
from app.ev import csvstore  # noqa: E402
from app.ev.belib import fetch_snapshot  # noqa: E402
from app.ev.rules import flags_json, load_csv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    try:
        points, at = fetch_snapshot()
    except FeedError as exc:
        print(f"FAILED: {exc}")
        return 1
    s = csvstore.record(args.data, points, at)
    print(
        f"{s.observed_at:%Y-%m-%d %H:%M:%S} UTC  points {s.points}  new events {s.new_events}  "
        f"restamped {s.restamped}  changed_same_time {s.changed_same_time}  "
        f"feed newest {s.feed_newest}  stale {s.stale}"
    )
    points_hist, cov = load_csv(args.data)
    report = flags_json(points_hist, cov)
    (args.data / "flags.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"flags.json: {len(report['flags'])} flags")  # type: ignore[arg-type]
    return 2 if s.stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
