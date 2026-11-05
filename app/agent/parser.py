"""Deterministic question parser (v1, no LLM). See docs/decisions.md D-009.

Extracts: intent, line (mode + short name), stop area. Never invents data:
if something is missing or ambiguous, the result says so and the dialog asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.data.stops import Line, StopIndex, StopMatch, normalize

_STATUS_WORDS = re.compile(
    r"\b(perturbation|perturbations|trafic|traffic|incident|incidents|probleme|problemes|"
    r"panne|greve|retard|retards|travaux|disruption|disruptions|delay|delays|status|statut|"
    r"fonctionne|marche|working|running|info|infos)\b"
)

# Number words the speech recogniser may return instead of digits
_NUMBER_WORDS = {
    "un": "1",
    "une": "1",
    "one": "1",
    "deux": "2",
    "two": "2",
    "trois": "3",
    "three": "3",
    "quatre": "4",
    "four": "4",
    "cinq": "5",
    "five": "5",
    "six": "6",
    "sept": "7",
    "seven": "7",
    "huit": "8",
    "eight": "8",
    "neuf": "9",
    "nine": "9",
    "dix": "10",
    "ten": "10",
    "onze": "11",
    "eleven": "11",
    "douze": "12",
    "twelve": "12",
    "treize": "13",
    "thirteen": "13",
    "quatorze": "14",
    "fourteen": "14",
}
_NUM = r"(\d{1,2}(?:\s?bis)?|" + "|".join(_NUMBER_WORDS) + r")"

_LINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("RapidTransit", re.compile(r"\brer\s?([a-e])\b")),
    ("Tramway", re.compile(r"\b(?:tram|tramway)\s?t?\s?(\d{1,2}\s?[ab]?)\b")),
    ("Tramway", re.compile(r"\bt(\d{1,2}[ab]?)\b")),
    ("Metro", re.compile(r"\b(?:ligne|line|metro|m)\s?" + _NUM + r"\b")),
    ("LocalTrain", re.compile(r"\b(?:ligne|line|train|transilien)\s?([hjklnpru])\b")),
]


@dataclass
class ParsedQuery:
    intent: str  # next_departure | line_status | unknown
    line: Line | None = None
    line_heard: str | None = None  # line mentioned but not found in reference data
    stops: list[StopMatch] = field(default_factory=list)
    wants_english: bool = False

    @property
    def stop_ambiguous(self) -> bool:
        if len(self.stops) < 2:
            return False
        top, second = self.stops[0], self.stops[1]
        return top.score < 0.999 and top.score - second.score < 0.05


def _extract_line(text: str, index: StopIndex) -> tuple[Line | None, str | None, str]:
    """Return (line, heard_label, text_without_line_mention)."""
    for mode, pattern in _LINE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(1).replace(" ", "")
        short = _NUMBER_WORDS.get(raw, raw).replace("bis", "B")
        if mode == "Tramway":
            short = "T" + short
        elif mode == "RapidTransit" or mode == "LocalTrain":
            short = short.upper()
        line = index.find_line(mode, short)
        stripped = (text[: m.start()] + " " + text[m.end() :]).strip()
        return line, (None if line else f"{mode}:{short}"), stripped
    return None, None, text


def parse(utterance: str, index: StopIndex) -> ParsedQuery:
    text = normalize(utterance)
    if not text:
        return ParsedQuery("unknown")
    wants_english = bool(re.fullmatch(r"(in )?english( please)?|anglais", text))
    if wants_english:
        return ParsedQuery("unknown", wants_english=True)
    line, heard, rest = _extract_line(text, index)
    intent = "line_status" if _STATUS_WORDS.search(text) else "next_departure"
    if intent == "line_status":
        return ParsedQuery(intent, line=line, line_heard=heard)
    stops = index.match(rest, line=line) if rest else []
    if not stops and line is not None:
        # Line found but stop does not serve it: retry without the line filter
        stops = index.match(rest)
    if not stops and line is None and heard is None and not rest:
        return ParsedQuery("unknown")
    return ParsedQuery(intent, line=line, line_heard=heard, stops=stops)
