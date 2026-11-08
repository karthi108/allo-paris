"""Take one Belib' snapshot and store status changes in data/ev.db.

Usage:  python scripts/ev_collect.py            (one snapshot)
        python scripts/ev_collect.py --db PATH  (another database file)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.prim import FeedError  # noqa: E402
from app.ev.belib import fetch_snapshot  # noqa: E402
from app.ev.history import EvHistory  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ev.db")
    args = ap.parse_args()
    try:
        points, at = fetch_snapshot()
    except FeedError as exc:
        print(f"FAILED: {exc}")
        return 1
    hist = EvHistory(args.db)
    s = hist.record(points, at)
    print(
        f"snapshot {s.observed_at:%Y-%m-%d %H:%M:%S} UTC "
        f"(#{hist.snapshot_count()} in {args.db.name})"
    )
    print(f"points {s.points}  by status {s.by_status}")
    print(
        f"new events {s.new_events}  restamped {s.restamped}  "
        f"changed_same_time {s.changed_same_time}"
    )
    print(f"newest last_updated in feed: {s.feed_newest}")
    if s.stale:
        print("STALE: the feed has not moved since the previous snapshot (cached or frozen)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
