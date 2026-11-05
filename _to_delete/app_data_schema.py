"""Internal normalized schema. Every data result carries source, freshness and realtime flag."""

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    PRIM_NEXT_DEPARTURES = "prim_next_departures"
    IDFM_GTFS = "idfm_gtfs"
    IDFM_TRAFFIC = "idfm_traffic"
    VELIB_GBFS = "velib_gbfs"


class Freshness(BaseModel):
    source: Source
    fetched_at: datetime
    realtime: bool

    def age(self, now: datetime) -> timedelta:
        return now - self.fetched_at

    def is_stale(self, now: datetime, stale_after_seconds: int) -> bool:
        return self.realtime and self.age(now).total_seconds() > stale_after_seconds


class Departure(BaseModel):
    line_id: str
    line_name: str
    stop_id: str
    stop_name: str
    direction: str
    expected_at: datetime
    realtime: bool = Field(description="False means scheduled (GTFS) time")


class DeparturesResult(BaseModel):
    departures: list[Departure]
    freshness: Freshness
