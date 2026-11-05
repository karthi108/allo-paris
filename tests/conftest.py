"""Shared fixtures. Reference rows are real IDFM records captured 2026-11-05."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.data.prim import Departure, DeparturesResult, FeedError, TrafficResult
from app.data.stops import StopIndex, build_index_records

FIX = Path(__file__).parent / "fixtures"


def load_index() -> StopIndex:
    rows = json.loads((FIX / "arrets_lignes_sample.json").read_text(encoding="utf-8"))
    arr = json.loads((FIX / "arrets_sample.json").read_text(encoding="utf-8"))
    line_rows = [
        {"id": r[0], "shortname": r[1], "mode": r[2], "stop_id": r[3], "stop_name": r[4]}
        for r in rows
    ]
    arr_rows = [{"arrid": a, "zdaid": z} for a, z in arr]
    return StopIndex.from_records(build_index_records(line_rows, arr_rows))


@pytest.fixture
def index() -> StopIndex:
    return load_index()


class FakeSource:
    def __init__(self) -> None:
        self.down = False
        self.calls: list[tuple[str, str | None]] = []
        self.messages: list[str] = []
        self.realtime = True
        self.age = timedelta(seconds=10)

    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult:
        self.calls.append((monitoring_ref, line_id))
        if self.down:
            raise FeedError("down")
        now = datetime.now(UTC)
        deps = [
            Departure(
                line_id or "", "Porte de Clignancourt", now + timedelta(seconds=200), self.realtime
            ),
            Departure(
                line_id or "", "Bagneux - Lucie Aubrac", now + timedelta(seconds=130), self.realtime
            ),
            Departure(
                line_id or "", "Porte de Clignancourt", now + timedelta(seconds=430), self.realtime
            ),
        ]
        deps.sort(key=lambda d: d.at)
        return DeparturesResult(deps, now - self.age)

    def traffic(self, line_id: str) -> TrafficResult:
        if self.down:
            raise FeedError("down")
        return TrafficResult(self.messages, datetime.now(UTC))


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


def siri(visits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "Siri": {"ServiceDelivery": {"StopMonitoringDelivery": [{"MonitoredStopVisit": visits}]}}
    }
