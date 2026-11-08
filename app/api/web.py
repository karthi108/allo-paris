"""Web companion API logic, framework-free so it can be unit tested.

Same rules as the phone line: every time shown comes from PRIM, answers come
from the same templates, and limits protect the PRIM quota.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from app.agent.dialog import CallState, Dialog, drop_terminating, render_departures
from app.data.prim import FeedError
from app.data.stops import Line, StopArea, StopIndex

MAX_SESSIONS = 1000


class RateLimiter:
    """Fixed-window limiter per key (e.g. client IP)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        window = int((now if now is not None else time.time()) // 60)
        win, count = self._hits.get(key, (window, 0))
        if win != window:
            win, count = window, 0
        if count >= self.per_minute:
            self._hits[key] = (win, count)
            return False
        self._hits[key] = (win, count + 1)
        if len(self._hits) > 10_000:
            self._hits.clear()
        return True


def line_json(line: Line, lang: str = "fr") -> dict[str, str]:
    return {
        "id": line.line_id,
        "short": line.short,
        "mode": line.mode,
        "label": line.spoken(lang),
        "color": line.color,
        "text_color": line.text_color,
    }


def stop_json(area: StopArea) -> dict[str, Any]:
    return {
        "id": area.zda_id,
        "name": area.name,
        "lat": area.lat,
        "lon": area.lon,
        "lines": [line_json(ln) for ln in area.lines],
    }


class WebApi:
    def __init__(self, index: StopIndex, dialog: Dialog, stale_after: int = 120) -> None:
        self.index = index
        self.dialog = dialog
        self.stale_after = stale_after
        self.sessions: OrderedDict[str, CallState] = OrderedDict()
        self._stops_cache = self._group_stations()

    def _group_stations(self) -> list[dict[str, Any]]:
        """One map entry per station: merges same-name stop areas that are close together
        (e.g. Gare du Nord metro + RER). `ids` lists every stop area id it covers."""
        done: set[str] = set()
        out: list[dict[str, Any]] = []
        for area in self.index.areas:
            if area.zda_id in done or area.lat is None:
                continue
            group = self.index.siblings(area)
            done.update(a.zda_id for a in group)
            entry = stop_json(area)
            entry["ids"] = [a.zda_id for a in group]
            entry["lines"] = [line_json(ln) for ln in self.index.station_lines(area)]
            out.append(entry)
        return out

    def stops(self) -> list[dict[str, Any]]:
        return self._stops_cache

    def departures(self, stop_id: str, line_id: str, lang: str = "fr") -> dict[str, Any]:
        station = self.index.by_id.get(stop_id)
        if station is None:
            return {"error": "unknown_stop"}
        line = next((ln for ln in self.index.station_lines(station) if ln.line_id == line_id), None)
        if line is None:
            return {"error": "line_not_at_stop"}
        area = self.index.area_for_line(station, line) or station
        try:
            result = drop_terminating(
                self.dialog.source.next_departures(area.monitoring_ref, line.line_id), area
            )
        except FeedError:
            return {"error": "feed_down", "stop": stop_json(area), "line": line_json(line, lang)}
        now = datetime.now(UTC)
        age = int((now - result.fetched_at).total_seconds())
        stale = age > self.stale_after
        return {
            "stop": stop_json(area),
            "line": line_json(line, lang),
            "fetched_at": result.fetched_at.isoformat(),
            "age_seconds": max(age, 0),
            "stale": stale,
            "departures": []
            if stale
            else [
                {
                    "destination": d.destination,
                    "at": d.at.isoformat(),
                    "minutes": max(int((d.at - now).total_seconds() // 60), 0),
                    "realtime": d.realtime,
                }
                for d in result.departures[:10]
            ],
            "answer": render_departures(result, line, area, lang, now, self.stale_after),
        }

    def velib(self, stop_id: str) -> dict[str, Any]:
        area = self.index.by_id.get(stop_id)
        if area is None or area.lat is None or area.lon is None:
            return {"error": "unknown_stop"}
        bikes = self.dialog.bikes
        if bikes is None:
            return {"error": "feed_down"}
        try:
            result = bikes.nearby(area.lat, area.lon)
        except FeedError:
            return {"error": "feed_down"}
        return {
            "fetched_at": result.fetched_at.isoformat(),
            "stations": [
                {
                    "name": s.name,
                    "distance_m": s.distance_m,
                    "bikes": s.bikes,
                    "ebikes": s.ebikes,
                    "mechanical": s.mechanical,
                    "docks": s.docks,
                    "renting": s.renting,
                    "reported_at": s.reported_at.isoformat() if s.reported_at else None,
                    "lat": s.lat,
                    "lon": s.lon,
                }
                for s in result.stations
            ],
        }

    def traffic(self, line_id: str) -> dict[str, Any]:
        line = next((ln for a in self.index.areas for ln in a.lines if ln.line_id == line_id), None)
        if line is None:
            return {"error": "unknown_line"}
        try:
            result = self.dialog.source.traffic(line.line_id)
        except FeedError:
            return {"error": "feed_down", "line": line_json(line)}
        return {
            "line": line_json(line),
            "messages": result.messages[:3],
            "fetched_at": result.fetched_at.isoformat(),
        }

    def chargers(self, stop_id: str) -> dict[str, Any]:
        area = self.index.by_id.get(stop_id)
        if area is None or area.lat is None or area.lon is None:
            return {"error": "unknown_stop"}
        return self._chargers(area.lat, area.lon, 500, 3)

    def chargers_map(self) -> dict[str, Any]:
        """Every Belib' address (Paris is ~10 km across, so 20 km from the centre covers it)."""
        return self._chargers(48.8566, 2.3522, 20_000, 10_000)

    def _chargers(self, lat: float, lon: float, radius: int, limit: int) -> dict[str, Any]:
        chargers = self.dialog.chargers
        if chargers is None:
            return {"error": "feed_down"}
        try:
            res = chargers.nearby(lat, lon, radius, limit)
        except FeedError:
            return {"error": "feed_down"}
        return {
            "fetched_at": res.fetched_at.isoformat(),
            "reliability_as_of": res.flags_as_of.isoformat() if res.flags_as_of else None,
            "addresses": [
                {
                    "name": a.name,
                    "lat": a.lat,
                    "lon": a.lon,
                    "distance_m": a.distance_m,
                    "in_service": a.in_service,
                    "available": a.available,
                    "charging": a.charging,
                    "out_of_service": a.out_of_service,
                    "warnings": list(a.flags),
                }
                for a in res.addresses
            ],
        }

    def ask(self, question: str, session_id: str, lang: str = "fr") -> dict[str, Any]:
        question = question.strip()[:300]
        state = self.sessions.get(session_id)
        if state is None:
            state = CallState(lang=lang)
            self.sessions[session_id] = state
            if len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        state.lang = lang if lang in ("fr", "en") else "fr"
        if not question:
            return {"intent": "empty", "answer": ""}
        reply = self.dialog.handle(question, state)
        return {
            "intent": reply.intent,
            "path": reply.path,
            "latency_ms": reply.latency_ms,
            "tools": reply.tools,
            "answer": reply.text,
            "lang": state.lang,
            "stop": stop_json(reply.stop) if reply.stop else None,
            "line": line_json(reply.line, state.lang) if reply.line else None,
            "focus": list(reply.focus) if reply.focus else None,
        }
