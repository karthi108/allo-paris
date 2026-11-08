"""Tools the LLM may call. Each returns plain JSON built only from live data sources.

Every output is kept in Toolbox.outputs so the grounding guard can check the final
answer against exactly what the tools returned (app/agent/grounding.py).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from app.agent.llm import ToolSpec
from app.agent.parser import LANDMARKS, _landmark
from app.data.prim import DeparturesResult, FeedError, TrafficResult
from app.data.routes import PARIS, Journey
from app.data.stops import Line, StopArea, StopIndex
from app.data.velib import VelibResult
from app.ev.live import ChargerResult


class Transit(Protocol):
    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult: ...
    def traffic(self, line_id: str) -> TrafficResult: ...


class Bikes(Protocol):
    def nearby(
        self, lat: float, lon: float, radius_m: int = 500, limit: int = 3
    ) -> VelibResult: ...


class Chargers(Protocol):
    def nearby(
        self, lat: float, lon: float, radius_m: int = 500, limit: int = 3
    ) -> ChargerResult: ...
    def find_address(self, query: str) -> tuple[float, float, str] | None: ...


class Planner(Protocol):
    def plan(
        self,
        from_lat: float,
        from_lon: float,
        to_lat: float,
        to_lon: float,
        depart_at: datetime | None = None,
    ) -> list[Journey]: ...


TOOLS = [
    ToolSpec(
        "find_station",
        "Find metro/RER/tram/train stations by name or landmark (typos allowed). "
        "Returns station ids and the lines serving each. Call this first for any place.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Station or landmark"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        "next_departures",
        "Live next departures for one line at one station (real-time IDFM data).",
        {
            "type": "object",
            "properties": {
                "station_id": {"type": "string"},
                "line_id": {"type": "string", "description": "line_id from find_station"},
            },
            "required": ["station_id", "line_id"],
        },
    ),
    ToolSpec(
        "line_status",
        "Current disruption / works messages for a line.",
        {
            "type": "object",
            "properties": {"line_id": {"type": "string"}},
            "required": ["line_id"],
        },
    ),
    ToolSpec(
        "velib_nearby",
        "Live Vélib' bikes, e-bikes and free docks within 500 m of a station.",
        {
            "type": "object",
            "properties": {"station_id": {"type": "string"}},
            "required": ["station_id"],
        },
    ),
    ToolSpec(
        "chargers_nearby",
        "Belib' public EV chargers (City of Paris network) within 500 m: live status per "
        "address (free, charging, out of service) and reliability warnings computed from "
        "their observed history. Give station_id (from find_station) OR place (a street or "
        "landmark name, e.g. 'Panthéon').",
        {
            "type": "object",
            "properties": {
                "station_id": {"type": "string"},
                "place": {"type": "string"},
            },
        },
    ),
    ToolSpec(
        "plan_route",
        "Journey from one station to another with IDFM's official planner. Returns up to 3 "
        "journeys with legs, total minutes and current disruption messages on the lines used. "
        "depart_at: local Paris time 'YYYY-MM-DDTHH:MM'. Required when the user names a day or "
        "time (tomorrow, demain, 8h, lundi, ce soir); omit only for leaving now (real-time).",
        {
            "type": "object",
            "properties": {
                "from_station_id": {"type": "string"},
                "to_station_id": {"type": "string"},
                "depart_at": {"type": "string"},
            },
            "required": ["from_station_id", "to_station_id"],
        },
    ),
]


class ToolError(Exception):
    pass


def _line_json(line: Line) -> dict[str, str]:
    return {"line_id": line.line_id, "label": line.spoken("en"), "mode": line.mode}


class Toolbox:
    def __init__(
        self,
        index: StopIndex,
        transit: Transit,
        bikes: Bikes | None = None,
        planner: Planner | None = None,
        chargers: Chargers | None = None,
    ) -> None:
        self.index = index
        self.chargers = chargers
        self.transit = transit
        self.bikes = bikes
        self.planner = planner
        self.outputs: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        try:
            fn = getattr(self, f"_t_{name}", None)
            if fn is None:
                raise ToolError(f"unknown tool {name}")
            out: dict[str, Any] = fn(**args)
        except FeedError as exc:
            out = {"error": "data source unavailable", "detail": str(exc)}
        except (ToolError, TypeError, ValueError) as exc:
            out = {"error": str(exc)}
        self.outputs.append({"_tool": name, **out})  # tool name kept for the grounding guard
        return json.dumps(out, ensure_ascii=False)

    def _area(self, station_id: str) -> StopArea:
        area = self.index.by_id.get(str(station_id))
        if area is None:
            raise ToolError(f"unknown station_id {station_id}; call find_station first")
        return area

    def _line(self, area: StopArea, line_id: str) -> tuple[StopArea, Line]:
        for ln in self.index.station_lines(area):
            if ln.line_id == line_id:
                served = self.index.area_for_line(area, ln) or area
                return served, ln
        raise ToolError(f"line {line_id} does not serve {area.name}")

    # ---------- tools ----------
    def _t_find_station(self, query: str) -> dict[str, Any]:
        matches = self.index.match(str(query)[:120], limit=5)
        landmark = _landmark(str(query))
        if landmark and (not matches or matches[0].score < 0.95 or landmark[2] >= 0.95):
            near = self.index.match(landmark[1], limit=1)
            if near and near[0].score >= 0.95:
                matches = near + [m for m in matches if m.area is not near[0].area]
        seen: set[str] = set()
        out = []
        for m in matches:
            if m.area.zda_id in seen:
                continue
            seen.update(a.zda_id for a in self.index.siblings(m.area))
            out.append(
                {
                    "station_id": m.area.zda_id,
                    "name": m.area.name,
                    "match": round(m.score, 2),
                    "lines": [_line_json(ln) for ln in self.index.station_lines(m.area)],
                }
            )
        result: dict[str, Any] = {"stations": out[:4]}
        if landmark and landmark[2] >= 0.8:
            result["landmark"] = {"place": landmark[0], "nearest_station": landmark[1]}
        return result

    def _t_next_departures(self, station_id: str, line_id: str) -> dict[str, Any]:
        from app.agent.dialog import drop_terminating

        area, line = self._line(self._area(station_id), line_id)
        res = drop_terminating(
            self.transit.next_departures(area.monitoring_ref, line.line_id), area
        )
        now = datetime.now(UTC)
        age = int((now - res.fetched_at).total_seconds())
        return {
            "station": area.name,
            "line": line.spoken("en"),
            "data_age_seconds": max(age, 0),
            "departures": [
                {
                    "towards": d.destination,
                    "in_minutes": max(int((d.at - now).total_seconds() // 60), 0),
                    "at": d.at.astimezone(PARIS).strftime("%H:%M"),
                    "realtime": d.realtime,
                }
                for d in res.departures[:6]
            ],
        }

    def _t_line_status(self, line_id: str) -> dict[str, Any]:
        line = next((ln for a in self.index.areas for ln in a.lines if ln.line_id == line_id), None)
        if line is None:
            raise ToolError(f"unknown line_id {line_id}")
        res = self.transit.traffic(line.line_id)
        return {"line": line.spoken("en"), "messages": res.messages[:3]}

    def _t_velib_nearby(self, station_id: str) -> dict[str, Any]:
        area = self._area(station_id)
        if self.bikes is None or area.lat is None or area.lon is None:
            raise ToolError("Vélib data not available")
        res = self.bikes.nearby(area.lat, area.lon)
        return {
            "near": area.name,
            "stations": [
                {
                    "name": s.name,
                    "distance_m": s.distance_m,
                    "bikes": s.bikes,
                    "ebikes": s.ebikes,
                    "free_docks": s.docks,
                    "open": s.renting,
                }
                for s in res.stations
            ],
        }

    def _t_chargers_nearby(
        self, station_id: str | None = None, place: str | None = None
    ) -> dict[str, Any]:
        if self.chargers is None:
            raise ToolError("charger data not available")
        if station_id:
            area = self._area(station_id)
            if area.lat is None or area.lon is None:
                raise ToolError("missing coordinates")
            lat, lon, near = area.lat, area.lon, area.name
        elif place:
            found = self.chargers.find_address(str(place)[:120])
            if found is None:
                raise ToolError(f"no Belib' address matches {place!r}; try find_station")
            lat, lon, near = found
        else:
            raise ToolError("give station_id or place")
        res = self.chargers.nearby(lat, lon)
        return {
            "near": near,
            "source": "Belib' (City of Paris), real-time",
            "reliability_as_of": res.flags_as_of.isoformat(timespec="minutes")
            if res.flags_as_of
            else "not available",
            "addresses": [
                {
                    "address": a.name,
                    "distance_m": a.distance_m,
                    "points_in_service": a.in_service,
                    "free": a.available,
                    "charging": a.charging,
                    "out_of_service": a.out_of_service,
                    "reliability_warnings": list(a.flags),
                }
                for a in res.addresses
            ],
        }

    def _t_plan_route(
        self, from_station_id: str, to_station_id: str, depart_at: str | None = None
    ) -> dict[str, Any]:
        if self.planner is None:
            raise ToolError("route planner not available")
        a, b = self._area(from_station_id), self._area(to_station_id)
        if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
            raise ToolError("missing coordinates")
        when = None
        if depart_at:
            try:
                when = datetime.fromisoformat(str(depart_at)).replace(tzinfo=PARIS)
            except ValueError as exc:
                raise ToolError("depart_at must be YYYY-MM-DDTHH:MM") from exc
        journeys = self.planner.plan(a.lat, a.lon, b.lat, b.lon, depart_at=when)
        disruptions: dict[str, list[str]] = {}
        for j in journeys:
            for leg in j.legs:
                if leg.kind != "transit" or not leg.line or leg.line in disruptions:
                    continue
                line = self.index.find_line(leg.mode if leg.mode != "Bus" else None, leg.line)
                if line is None:
                    continue
                try:
                    msgs = self.transit.traffic(line.line_id).messages[:2]
                except FeedError:
                    msgs = []
                if msgs:
                    disruptions[leg.line] = msgs
        return {
            "from": a.name,
            "to": b.name,
            "planned_for": depart_at or "now (real-time)",
            "journeys": [
                {
                    "total_minutes": j.minutes,
                    "depart": j.depart,
                    "arrive": j.arrive,
                    "changes": j.transfers,
                    "walking_minutes": j.walk_minutes,
                    "legs": [
                        {
                            "line": leg.line,
                            "mode": leg.mode,
                            "towards": leg.direction,
                            "from": leg.from_name,
                            "to": leg.to_name,
                            "minutes": leg.minutes,
                            "depart": leg.depart,
                        }
                        for leg in j.legs
                        if leg.kind == "transit"
                    ],
                }
                for j in journeys
            ],
            "disruptions_on_lines_used": disruptions,
        }


def landmark_names() -> list[str]:
    return sorted({v[1] for v in LANDMARKS.values()})
