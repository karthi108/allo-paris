"""Ask a question in the terminal against LIVE PRIM data (no phone needed).

Usage:
  python scripts/ask.py "prochain RER A à Châtelet"
  python scripts/ask.py --en "next line 4 at Gare du Nord"
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.dialog import CallState, Dialog  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.prim import PrimClient  # noqa: E402
from app.data.stops import StopIndex  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    lang = "en" if args and args[0] == "--en" else "fr"
    question = " ".join(a for a in args if a != "--en")
    if not question:
        sys.exit(__doc__)
    s = get_settings()
    if not s.prim_api_key:
        sys.exit("ALLO_PRIM_API_KEY missing in .env")
    dialog = Dialog(StopIndex.load(s.stops_path), PrimClient(s.prim_api_key))
    state = CallState(lang=lang)
    t0 = time.perf_counter()
    reply = dialog.handle(question, state)
    print(f"[{reply.intent}] {reply.text}")
    print(f"({(time.perf_counter() - t0) * 1000:.0f} ms)")


if __name__ == "__main__":
    main()
