"""Reliability report from the collected history (rules R1-R4, provisional thresholds).

Usage:  python scripts/ev_report.py --data PATH_TO_EV_DATA_CHECKOUT [--examples 5]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ev.rules import Thresholds, evaluate, load_csv  # noqa: E402

NAMES = {"R1": "stuck out of service", "R2": "ghost available", "R3": "flapping", "R4": "silent"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--examples", type=int, default=5)
    args = ap.parse_args()
    points, cov = load_csv(args.data)
    if cov.first is None or cov.last is None:
        print("No good snapshots yet.")
        return 1
    th = Thresholds()
    span = cov.last - cov.first
    covered = cov.covered(cov.first, cov.last)
    print(f"Coverage {cov.first:%Y-%m-%d %H:%M} -> {cov.last:%Y-%m-%d %H:%M} UTC")
    print(
        f"  span {span.total_seconds() / 3600:.1f} h, "
        f"covered {covered.total_seconds() / 3600:.1f} h, "
        f"gaps {cov.gaps}, stale snapshots {cov.stale}"
    )
    print(f"Thresholds (PROVISIONAL): {th}")
    flags = evaluate(points, cov, th)
    print(f"Points {len(points)}, flags {len(flags)}")
    for rule, name in NAMES.items():
        fs = [f for f in flags if f.rule == rule]
        print(f"\n{rule} {name}: {len(fs)}")
        for f in sorted(fs, key=lambda f: -f.covered_hours)[: args.examples]:
            print(f"  {f.point_id}  {f.station}  ·  {f.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
