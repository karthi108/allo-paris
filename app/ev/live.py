"""Belib' chargers near a place: live status plus reliability flags.

Live status: the Belib' export (app/ev/belib.py), cached 60 s, one request for all points.
Reliability: flags.json written by the scheduled collector on the ev-data branch (rules
R1-R4, app/ev/rules.py), cached 10 minutes. If flags are unavailable, live status still
answers and the reply says nothing about reliability (never "reliable").
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.data.prim import FeedError
from app.data.stops import normalize
from app.data.velib import _dist
from app.ev.belib import PointStatus, fetch_snapshot

FLAGS_URL = "https://raw.githubusercontent.com/karthi108/allo-paris/ev-data/flags.json"
_POSTCODE = re.compile(r"\s*\b75\d{3}\b.*$", re.I)
# Words that say "charger" or "near", or are too common in Paris addresses to identify one
_NOT_PLACE = {
    "borne",
    "bornes",
    "recharge",
    "recharger",
    "belib",
    "charger",
    "chargers",
    "charging",
    "chargeur",
    "chargeurs",
    "electrique",
    "electric",
    "voiture",
    "pres",
    "proche",
    "near",
    "close",
    "where",
    "there",
    "working",
    "marche",
    "fonctionne",
    "libre",
    "libres",
    "free",
    "station",
    "stations",
    "paris",
    "avenue",
    "boulevard",
    "place",
    "quai",
    "rue",
    "square",
    "allee",
    "une",
    "des",
    "les",
    "pour",
    "avec",
    "dans",
    "quelle",
    "quel",
    "which",
    "some",
}


@dataclass(frozen=True)
class Address:
    name: str  # street address without postcode
    distance_m: int
    in_service: int  # points not "planned"
    available: int
    charging: int
    out_of_service: int  # maintenance + unknown
    flags: tuple[str, ...]  # reliability explanations from rules R1-R4


@dataclass(frozen=True)
class ChargerResult:
    addresses: list[Address]
    fetched_at: datetime
    flags_as_of: datetime | None  # None: reliability data unavailable


def short_address(station: str) -> str:
    return _POSTCODE.sub("", station).strip(" ,")


def _fetch_flags(url: str) -> dict[str, Any]:
    req = urllib.request.Request(  # noqa: S310 (fixed https URL)
        f"{url}?t={time.time_ns()}", headers={"User-Agent": "allo-paris"}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
        data: dict[str, Any] = json.load(resp)
    return data


class ChargerClient:
    def __init__(
        self,
        flags_url: str = FLAGS_URL,
        live_ttl: float = 60,
        flags_ttl: float = 600,
        fetch: Callable[[], tuple[list[PointStatus], datetime]] = fetch_snapshot,
        get_flags: Callable[[str], dict[str, Any]] = _fetch_flags,
    ) -> None:
        self.flags_url = flags_url
        self.live_ttl, self.flags_ttl = live_ttl, flags_ttl
        self._fetch, self._get_flags = fetch, get_flags
        self._live: tuple[float, list[PointStatus], datetime] | None = None
        self._flags: tuple[float, dict[str, Any]] | None = None
        self.last_error: str | None = None

    def _points(self) -> tuple[list[PointStatus], datetime]:
        if self._live and time.monotonic() - self._live[0] < self.live_ttl:
            return self._live[1], self._live[2]
        points, at = self._fetch()  # raises FeedError
        self._live = (time.monotonic(), points, at)
        return points, at

    def _flag_data(self) -> dict[str, Any] | None:
        if self._flags and time.monotonic() - self._flags[0] < self.flags_ttl:
            return self._flags[1]
        try:
            data = self._get_flags(self.flags_url)
        except Exception as exc:  # flags are optional: keep the last good copy
            self.last_error = f"flags: {type(exc).__name__}"
            return self._flags[1] if self._flags else None
        self._flags = (time.monotonic(), data)
        return data

    def find_address(self, query: str) -> tuple[float, float, str] | None:
        """Match place words ("Panthéon") against Belib' addresses. Returns centroid + name."""
        words = [w for w in normalize(query).split() if len(w) >= 4 and w not in _NOT_PLACE]
        if not words:
            return None
        points, _ = self._points()
        best: tuple[int, int, str] | None = None
        for station in {p.station for p in points if p.station}:
            tokens = set(normalize(station).split())
            hits = sum(1 for w in words if w in tokens)
            if hits and (best is None or (hits, -len(station)) > (best[0], best[1])):
                best = (hits, -len(station), station)
        if best is None:
            return None
        coords = [(p.lat, p.lon) for p in points if p.station == best[2] and p.lat and p.lon]
        if not coords:
            return None
        lat = sum(c[0] for c in coords if c[0]) / len(coords)
        lon = sum(c[1] for c in coords if c[1]) / len(coords)
        return lat, lon, short_address(best[2])

    def nearby(self, lat: float, lon: float, radius_m: int = 500, limit: int = 3) -> ChargerResult:
        points, at = self._points()
        groups: dict[str, list[PointStatus]] = {}
        for p in points:
            if p.station and p.lat is not None and p.lon is not None:
                groups.setdefault(p.station, []).append(p)
        data = self._flag_data()
        by_station: dict[str, list[str]] = {}
        for f in (data or {}).get("flags", []):
            by_station.setdefault(str(f.get("station", "")), []).append(str(f.get("detail", "")))
        out: list[Address] = []
        for station, pts in groups.items():
            clat = sum(p.lat or 0 for p in pts) / len(pts)
            clon = sum(p.lon or 0 for p in pts) / len(pts)
            d = _dist(lat, lon, clat, clon)
            if d > radius_m:
                continue
            live = [p for p in pts if p.status != "planned"]
            if not live:
                continue
            out.append(
                Address(
                    name=short_address(station),
                    distance_m=d,
                    in_service=len(live),
                    available=sum(p.status == "available" for p in live),
                    charging=sum(p.status == "charging" for p in live),
                    out_of_service=sum(p.status in ("maintenance", "unknown") for p in live),
                    flags=tuple(by_station.get(station, [])[:3]),
                )
            )
        out.sort(key=lambda a: a.distance_m)
        as_of = None
        if data and data.get("generated_at"):
            try:
                as_of = datetime.fromisoformat(str(data["generated_at"]))
            except ValueError:
                as_of = None
        return ChargerResult(out[:limit], at, as_of)

    def status(self) -> dict[str, object]:
        return {
            "live_cached_at": self._live[2].isoformat() if self._live else None,
            "flags_loaded": self._flags is not None,
            "last_error": self.last_error,
        }


_ = (FeedError, UTC)  # FeedError propagates from nearby(); UTC kept for callers' clarity
