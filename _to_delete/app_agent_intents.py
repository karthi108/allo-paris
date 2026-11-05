"""Intent contract between the LLM and deterministic tools. See docs/decisions.md D-001.

The LLM may only produce one of these objects. Anything that fails validation is
treated as Unknown and gets a fixed reply.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class NextDeparture(BaseModel):
    intent: Literal["next_departure"]
    stop: str = Field(min_length=1, max_length=120)
    line: str | None = Field(default=None, max_length=40)
    direction: str | None = Field(default=None, max_length=120)


class LineStatus(BaseModel):
    intent: Literal["line_status"]
    line: str = Field(min_length=1, max_length=40)


class VelibNearby(BaseModel):
    intent: Literal["velib_nearby"]
    place: str = Field(min_length=1, max_length=120)


class Unknown(BaseModel):
    intent: Literal["unknown"] = "unknown"


Intent = Annotated[
    NextDeparture | LineStatus | VelibNearby | Unknown, Field(discriminator="intent")
]

_adapter: TypeAdapter[NextDeparture | LineStatus | VelibNearby | Unknown] = TypeAdapter(Intent)


def parse_intent(raw_json: str) -> NextDeparture | LineStatus | VelibNearby | Unknown:
    """Validate LLM output. Never raises: invalid output becomes Unknown."""
    try:
        return _adapter.validate_json(raw_json)
    except ValueError:
        return Unknown()
