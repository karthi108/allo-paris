"""Belib' (City of Paris public charging network) live status, from Paris open data.

Dataset: belib-points-de-recharge-pour-vehicules-electriques-disponibilite-temps-reel
(verified 2026-11-08 in a browser: 2,036 charge points, 398 addresses, no API key).
One export call returns every point (about 520 KB), so a snapshot costs one request.

Fields used: id_pdc (charge point id), statut_pdc, last_updated, adresse_station,
arrondissement, coordonneesxy {lat, lon}. 30 points had no coordinates on 2026-11-08.

Not verified: whether last_updated is the time of the last status CHANGE or of the last
REPORT. app/ev/history.py measures it on every snapshot (see "restamped" and
"changed_same_time" counters) instead of assuming.
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

EXPORT_URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    "belib-points-de-recharge-pour-vehicules-electriques-disponibilite-temps-reel/"
    "exports/json?select=id_pdc,statut_pdc,last_updated,adresse_station,arrondissement,coordonneesxy"
)

# Raw values seen on 2026-11-08 -> normalized status. Anything else is kept as "other".
STATUS = {
    "Disponible": "available",
    "Occupé (en charge)": "charging",
    "En maintenance": "maintenance",
    "Inconnu": "unknown",
    "Mise en service planifiée": "planned",
}


@dataclass(frozen=True)
class PointStatus:
    point_id: str
    status: str  # normalized, see STATUS
    raw_status: str
    changed_at: datetime | None  # the feed's last_updated (meaning not verified yet)
    station: str  # address: the feed has no station id, points share an address
    arrondissement: str
    lat: float | None
    lon: float | None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def parse_export(rows: Any) -> list[PointStatus]:
    if not isinstance(rows, list):
        raise FeedError("unexpected Belib' structure: expected a list")
    out: list[PointStatus] = []
    seen: set[str] = set()
    for r in rows:
        if not isinstance(r, dict) or not r.get("id_pdc"):
            continue
        pid = str(r["id_pdc"])
        if pid in seen:
            continue
        seen.add(pid)
        raw = str(r.get("statut_pdc") or "")
        geo = r.get("coordonneesxy") or {}
        lat, lon = geo.get("lat"), geo.get("lon")
        out.append(
            PointStatus(
                point_id=pid,
                status=STATUS.get(raw, "other"),
                raw_status=raw,
                changed_at=_time(r.get("last_updated")),
                station=str(r.get("adresse_station") or "").strip(),
                arrondissement=str(r.get("arrondissement") or "").strip(),
                lat=float(lat) if lat is not None else None,
                lon=float(lon) if lon is not None else None,
            )
        )
    return out


def snapshot_url(nonce: int) -> str:
    """Export URL made unique per request with an always-true filter.

    On 2026-11-08 the plain URL returned copies up to 22 minutes old to the collector, even
    with no-cache headers, while the browser got fresh data. A unique URL cannot be served
    from a cache. Verified in a browser the same day: all 2,036 rows, newest 3 s old.
    The "OR n = n" part keeps rows whose last_updated is empty.
    """
    where = f"last_updated < date'2100-01-01' OR {nonce} = {nonce}"
    return f"{EXPORT_URL}&where={urllib.parse.quote(where)}"


def fetch_snapshot(timeout: float = 30.0) -> tuple[list[PointStatus], datetime]:
    req = urllib.request.Request(  # noqa: S310 (fixed https URL)
        snapshot_url(time.time_ns()),
        headers={
            "Accept": "application/json",
            "User-Agent": "allo-paris-collector",
            # Not enough on their own (see snapshot_url); history.py also flags stale data
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            rows = json.load(resp)
    except Exception as exc:
        raise FeedError(f"Belib' request failed: {type(exc).__name__}") from exc
    return parse_export(rows), datetime.now(UTC)
