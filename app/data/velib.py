"""Vélib' live availability from the City of Paris open data (Opendatasoft API).

Dataset: velib-disponibilite-en-temps-reel (verified 2026-11-07). No API key.
Fields used: stationcode, name, numbikesavailable, mechanical, ebike, numdocksavailable,
is_renting, is_returning, duedate (station's last report), coordonnees_geo {lat, lon}.
The operator's own GBFS feed sits behind a bot check, so it is not used.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.data.prim import FeedError

URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    "velib-disponibilite-en-temps-reel/records"
)


@dataclass(frozen=True)
class VelibStation:
    code: str
    name: str
    bikes: int
    ebikes: int
    mechanical: int
    docks: int
    renting: bool
    returning: bool
    reported_at: datetime | None
    lat: float
    lon: float
    distance_m: int


@dataclass(frozen=True)
class VelibResult:
    stations: list[VelibStation]
    fetched_at: datetime


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _dist(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    from math import asin, cos, radians, sin, sqrt

    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return round(2 * 6_371_000 * asin(sqrt(h)))


def parse_records(payload: dict[str, Any], lat: float, lon: float) -> list[VelibStation]:
    try:
        rows = payload["results"]
    except (KeyError, TypeError) as exc:
        raise FeedError("unexpected Vélib structure") from exc
    out: list[VelibStation] = []
    for r in rows:
        geo = r.get("coordonnees_geo") or {}
        if "lat" not in geo or "lon" not in geo:
            continue
        reported = None
        if r.get("duedate"):
            try:
                reported = datetime.fromisoformat(str(r["duedate"]).replace("Z", "+00:00"))
            except ValueError:
                reported = None
        out.append(
            VelibStation(
                code=str(r.get("stationcode", "")),
                name=str(r.get("name", "?")),
                bikes=_int(r.get("numbikesavailable")),
                ebikes=_int(r.get("ebike")),
                mechanical=_int(r.get("mechanical")),
                docks=_int(r.get("numdocksavailable")),
                renting=str(r.get("is_renting", "")).upper() == "OUI",
                returning=str(r.get("is_returning", "")).upper() == "OUI",
                reported_at=reported,
                lat=float(geo["lat"]),
                lon=float(geo["lon"]),
                distance_m=_dist(lat, lon, float(geo["lat"]), float(geo["lon"])),
            )
        )
    out.sort(key=lambda s: s.distance_m)
    return out


class VelibClient:
    def __init__(self, cache_ttl: int = 60, timeout: float = 4.0, daily_budget: int = 2000) -> None:
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.daily_budget = daily_budget
        self._cache: dict[str, tuple[float, VelibResult]] = {}
        self.calls_today = 0
        self._day = datetime.now(UTC).date()
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None

    def nearby(self, lat: float, lon: float, radius_m: int = 500, limit: int = 3) -> VelibResult:
        key = f"{lat:.4f},{lon:.4f},{radius_m},{limit}"
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self.calls_today = today, 0
        if self.calls_today >= self.daily_budget:
            raise FeedError("daily Vélib budget reached")
        self.calls_today += 1
        point = f"geom'POINT({lon} {lat})'"
        query = urllib.parse.urlencode(
            {
                "where": f"within_distance(coordonnees_geo, {point}, {radius_m}m)",
                "order_by": f"distance(coordonnees_geo, {point})",
                "limit": str(limit),
            }
        )
        req = urllib.request.Request(  # noqa: S310 (fixed https base)
            f"{URL}?{query}", headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                payload: dict[str, Any] = json.load(resp)
        except Exception as exc:
            self.last_error = f"velib: {type(exc).__name__}"
            raise FeedError(f"Vélib request failed: {type(exc).__name__}") from exc
        result = VelibResult(parse_records(payload, lat, lon), datetime.now(UTC))
        self.last_ok_at = result.fetched_at
        self._cache[key] = (time.monotonic(), result)
        if len(self._cache) > 500:
            self._cache.clear()
        return result

    def status(self) -> dict[str, object]:
        return {
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "last_error": self.last_error,
            "calls_today": self.calls_today,
            "daily_budget": self.daily_budget,
        }
