"""IDFM PRIM client: next departures (SIRI Lite stop-monitoring) and traffic messages.

Response paths follow the PRIM SIRI Lite format:
  Siri.ServiceDelivery.StopMonitoringDelivery[0].MonitoredStopVisit[].MonitoredVehicleJourney
PRIM doc: times are UTC except ResponseTimestamp. Multi-line stops must be filtered on LineRef.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

BASE = "https://prim.iledefrance-mobilites.fr/marketplace"


class FeedError(Exception):
    """Data source failed or returned something unusable."""


@dataclass(frozen=True)
class Departure:
    line_id: str
    destination: str
    at: datetime
    realtime: bool  # False = only the scheduled (aimed) time was available


@dataclass(frozen=True)
class DeparturesResult:
    departures: list[Departure]
    fetched_at: datetime


@dataclass(frozen=True)
class TrafficResult:
    messages: list[str]
    fetched_at: datetime


def _value(obj: Any) -> str:
    """SIRI Lite wraps strings as {"value": ...} or [{"value": ...}]."""
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        obj = obj.get("value")
    return str(obj) if obj is not None else ""


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_stop_monitoring(
    payload: dict[str, Any], line_id: str | None, now: datetime
) -> list[Departure]:
    try:
        deliveries = payload["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"]
    except (KeyError, TypeError) as exc:
        raise FeedError("unexpected stop-monitoring structure") from exc
    out: list[Departure] = []
    for delivery in deliveries or []:
        for visit in delivery.get("MonitoredStopVisit") or []:
            journey = visit.get("MonitoredVehicleJourney") or {}
            ref = _value(journey.get("LineRef"))
            if line_id and f":{line_id}:" not in ref and not ref.endswith(line_id):
                continue
            call = journey.get("MonitoredCall") or {}
            expected = _parse_time(call.get("ExpectedDepartureTime")) or _parse_time(
                call.get("ExpectedArrivalTime")
            )
            aimed = _parse_time(call.get("AimedDepartureTime")) or _parse_time(
                call.get("AimedArrivalTime")
            )
            at = expected or aimed
            if at is None or at < now:
                continue
            destination = (
                _value(journey.get("DestinationName"))
                or _value(call.get("DestinationDisplay"))
                or _value(journey.get("DirectionName"))
            )
            out.append(
                Departure(
                    line_id=ref.strip(":").rsplit(":", 1)[-1] if ref else (line_id or ""),
                    destination=destination or "?",
                    at=at,
                    realtime=expected is not None,
                )
            )
    out.sort(key=lambda d: d.at)
    return out


def parse_general_message(payload: dict[str, Any]) -> list[str]:
    try:
        deliveries = payload["Siri"]["ServiceDelivery"]["GeneralMessageDelivery"]
    except (KeyError, TypeError) as exc:
        raise FeedError("unexpected general-message structure") from exc
    messages: list[str] = []
    for delivery in deliveries or []:
        for msg in delivery.get("InfoMessage") or []:
            content = msg.get("Content") or {}
            for m in content.get("Message") or []:
                text = " ".join(_value(m.get("MessageText")).split())
                if text:
                    _add_unique(messages, text)
    return messages


def _add_unique(messages: list[str], text: str) -> None:
    """PRIM often sends a short title and a long body that repeat each other.
    Keep one: if two messages share their first 40 characters, keep the longer."""
    key = text[:40].lower()
    for i, existing in enumerate(messages):
        if existing[:40].lower() == key or text in existing or existing in text:
            if len(text) > len(existing):
                messages[i] = text
            return
    messages.append(text)


class PrimClient:
    def __init__(
        self, api_key: str, cache_ttl: int = 30, timeout: float = 4.0, daily_budget: int = 900
    ) -> None:
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.daily_budget = daily_budget  # stay under the PRIM account quota
        self._cache: dict[str, tuple[float, datetime, dict[str, Any]]] = {}
        self.calls_made = 0
        self.calls_today = 0
        self._day = datetime.now(UTC).date()
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None

    def status(self) -> dict[str, object]:
        return {
            "configured": bool(self.api_key),
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "calls_today": self.calls_today,
            "daily_budget": self.daily_budget,
        }

    def _get(self, path: str, params: dict[str, str]) -> tuple[datetime, dict[str, Any]]:
        if not self.api_key:
            raise FeedError("PRIM API key not configured")
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1], cached[2]
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self.calls_today = today, 0
        if self.calls_today >= self.daily_budget:
            raise FeedError("daily PRIM budget reached")
        self.calls_today += 1
        req = urllib.request.Request(  # noqa: S310 (fixed https base)
            url, headers={"apikey": self.api_key, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                payload: dict[str, Any] = json.load(resp)
        except Exception as exc:  # network, HTTP, JSON: all treated as feed failure
            self.last_error = f"{path}: {type(exc).__name__}"
            self.last_error_at = datetime.now(UTC)
            raise FeedError(f"{path} request failed: {type(exc).__name__}") from exc
        self.calls_made += 1
        fetched_at = datetime.now(UTC)
        self.last_ok_at = fetched_at
        self._cache[url] = (time.monotonic(), fetched_at, payload)
        return fetched_at, payload

    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult:
        fetched_at, payload = self._get("stop-monitoring", {"MonitoringRef": monitoring_ref})
        deps = parse_stop_monitoring(payload, line_id, datetime.now(UTC))
        return DeparturesResult(deps, fetched_at)

    def traffic(self, line_id: str) -> TrafficResult:
        fetched_at, payload = self._get("general-message", {"LineRef": f"STIF:Line::{line_id}:"})
        return TrafficResult(parse_general_message(payload), fetched_at)
