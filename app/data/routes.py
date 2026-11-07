"""Journey planning through IDFM's official calculator (Navitia, via PRIM).

Format follows the Navitia journeys API (doc.navitia.io): from/to as "lon;lat",
datetime "YYYYMMDDTHHMMSS" in local Paris time, response journeys[].sections[].
data_freshness=realtime so planned journeys account for live disruptions where IDFM
provides them. The PRIM base URL is configurable (ALLO_NAVITIA_URL) and checked with
scripts/check_routes.py, because PRIM's public docs do not state it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.data.prim import FeedError

PARIS = ZoneInfo("Europe/Paris")
DEFAULT_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/journeys"

# Navitia commercial_mode names -> our mode names (stops.json)
MODE_MAP = {
    "metro": "Metro",
    "métro": "Metro",
    "rer": "RapidTransit",
    "tramway": "Tramway",
    "tram": "Tramway",
    "transilien": "LocalTrain",
    "train": "LocalTrain",
    "ter": "LocalTrain",
    "bus": "Bus",
    "noctilien": "Bus",
}


@dataclass(frozen=True)
class Leg:
    kind: str  # "transit" | "walk" | "wait" | "transfer"
    minutes: int
    mode: str = ""  # Metro, RapidTransit, Tramway, LocalTrain, Bus (transit legs)
    line: str = ""  # short code, e.g. "B", "4", "T2"
    direction: str = ""
    from_name: str = ""
    to_name: str = ""
    depart: str = ""  # HH:MM Paris time
    arrive: str = ""


@dataclass(frozen=True)
class Journey:
    minutes: int
    depart: str  # HH:MM
    arrive: str
    transfers: int
    walk_minutes: int
    legs: list[Leg] = field(default_factory=list)
    tag: str = ""  # Navitia "type": best, rapid, comfort, less_fallback_walk, ...


def _clock(raw: str | None) -> str:
    """Navitia '20261107T183000' -> '18:30'."""
    if not raw or "T" not in raw:
        return ""
    t = raw.split("T", 1)[1]
    return f"{t[0:2]}:{t[2:4]}" if len(t) >= 4 else ""


def _minutes(seconds: Any) -> int:
    try:
        return max(0, round(int(seconds) / 60))
    except (TypeError, ValueError):
        return 0


def parse_journeys(payload: dict[str, Any], limit: int = 3) -> list[Journey]:
    if not isinstance(payload, dict) or "journeys" not in payload:
        if isinstance(payload, dict) and payload.get("error"):
            return []  # e.g. no solution found between the two points
        raise FeedError("unexpected journeys structure")
    out: list[Journey] = []
    for j in payload.get("journeys") or []:
        legs: list[Leg] = []
        walk = 0
        for s in j.get("sections") or []:
            stype = s.get("type", "")
            mins = _minutes(s.get("duration"))
            if stype == "public_transport":
                info = s.get("display_informations") or {}
                cm = str(info.get("commercial_mode") or info.get("physical_mode") or "").lower()
                legs.append(
                    Leg(
                        kind="transit",
                        minutes=mins,
                        mode=MODE_MAP.get(cm, cm.title()),
                        line=str(info.get("code") or info.get("label") or ""),
                        direction=str(info.get("direction") or info.get("headsign") or ""),
                        from_name=str((s.get("from") or {}).get("name") or ""),
                        to_name=str((s.get("to") or {}).get("name") or ""),
                        depart=_clock(s.get("departure_date_time")),
                        arrive=_clock(s.get("arrival_date_time")),
                    )
                )
            elif stype in ("street_network", "crow_fly") or s.get("mode") == "walking":
                if mins:
                    walk += mins
                    legs.append(Leg(kind="walk", minutes=mins))
            elif stype == "transfer":
                walk += mins
                if mins:
                    legs.append(Leg(kind="transfer", minutes=mins))
            elif stype == "waiting" and mins:
                legs.append(Leg(kind="wait", minutes=mins))
        if not any(leg.kind == "transit" for leg in legs):
            continue  # walking-only suggestion: not useful for a transit assistant
        out.append(
            Journey(
                minutes=_minutes(j.get("duration")),
                depart=_clock(j.get("departure_date_time")),
                arrive=_clock(j.get("arrival_date_time")),
                transfers=int(j.get("nb_transfers") or 0),
                walk_minutes=walk,
                legs=legs,
                tag=str(j.get("type") or ""),
            )
        )
    out.sort(key=lambda x: x.minutes)
    return out[:limit]


class RouteClient:
    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_URL,
        cache_ttl: int = 60,
        timeout: float = 8.0,
        daily_budget: int = 300,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.daily_budget = daily_budget
        self._cache: dict[str, tuple[float, list[Journey]]] = {}
        self.calls_today = 0
        self._day = datetime.now(PARIS).date()
        self.last_error: str | None = None

    def plan(
        self,
        from_lat: float,
        from_lon: float,
        to_lat: float,
        to_lon: float,
        depart_at: datetime | None = None,
    ) -> list[Journey]:
        if not self.api_key:
            raise FeedError("PRIM API key not configured")
        when = (depart_at or datetime.now(PARIS)).astimezone(PARIS)
        params = {
            "from": f"{from_lon:.6f};{from_lat:.6f}",
            "to": f"{to_lon:.6f};{to_lat:.6f}",
            "datetime": when.strftime("%Y%m%dT%H%M%S"),
            "data_freshness": "realtime" if depart_at is None else "base_schedule",
            "count": "3",
        }
        query = urllib.parse.urlencode(params)
        minute = when.strftime("%Y%m%d%H%M")
        key = f"{params['from']}|{params['to']}|{minute}|{params['data_freshness']}"
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        today = datetime.now(PARIS).date()
        if today != self._day:
            self._day, self.calls_today = today, 0
        if self.calls_today >= self.daily_budget:
            raise FeedError("daily route budget reached")
        self.calls_today += 1
        req = urllib.request.Request(  # noqa: S310 (configured https URL)
            f"{self.url}?{query}", headers={"apikey": self.api_key, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                payload: dict[str, Any] = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # Navitia answers 404 + error body when no journey exists
                return []
            self.last_error = f"routes: HTTP {exc.code}"
            raise FeedError(f"route request failed: HTTP {exc.code}") from exc
        except Exception as exc:
            self.last_error = f"routes: {type(exc).__name__}"
            raise FeedError(f"route request failed: {type(exc).__name__}") from exc
        journeys = parse_journeys(payload)
        self._cache[key] = (time.monotonic(), journeys)
        if len(self._cache) > 300:
            self._cache.clear()
        return journeys

    def status(self) -> dict[str, object]:
        return {
            "calls_today": self.calls_today,
            "daily_budget": self.daily_budget,
            "last_error": self.last_error,
        }
