"""Find the working PRIM journey-planner URL with your key (one-off check).

Tries the candidate URLs with a Gare du Nord -> Bir-Hakeim request and prints which one
answers with journeys. Put the working one in .env as ALLO_NAVITIA_URL if it is not the
default. Uses at most 4 PRIM requests.

Usage:  python scripts/check_routes.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.data.routes import parse_journeys  # noqa: E402

BASE = "https://prim.iledefrance-mobilites.fr/marketplace"
CANDIDATES = [
    f"{BASE}/v2/navitia/journeys",
    f"{BASE}/v2/navitia/coverage/fr-idf/journeys",
    f"{BASE}/navitia/journeys",
    f"{BASE}/navitia/coverage/fr-idf/journeys",
]


def main() -> None:
    key = get_settings().prim_api_key
    if not key:
        sys.exit("ALLO_PRIM_API_KEY missing in .env")
    when = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y%m%dT%H%M%S")
    q = urllib.parse.urlencode(
        {"from": "2.355300;48.880900", "to": "2.289400;48.853900", "datetime": when, "count": "2"}
    )
    for url in CANDIDATES:
        headers = {"apikey": key, "Accept": "application/json"}
        req = urllib.request.Request(f"{url}?{q}", headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code:<4} {url}")
            continue
        except Exception as exc:
            print(f"{type(exc).__name__:<9} {url}")
            continue
        journeys = parse_journeys(payload)
        print(f"OK        {url}  -> {len(journeys)} journeys")
        for j in journeys:
            legs = " > ".join(f"{leg.line}" for leg in j.legs if leg.kind == "transit")
            print(f"          {j.minutes} min, {j.transfers} changes: {legs}")
        if journeys:
            print("\nWorking URL. If different from the default, add to .env:")
            print(f"ALLO_NAVITIA_URL={url}")
            return
    print("\nNo candidate worked. Check your PRIM subscription and send me the errors above.")


if __name__ == "__main__":
    main()
