"""Grounding guard: an LLM answer may only state numbers and lines the tools returned.

Checks:
- every number in the answer (minutes, times, counts, distances) appears in tool output
- every line mentioned (ligne 4, RER B, T2, line 14, metro 1) appears in tool output
If anything fails, the agent retries once with the problems listed, then falls back to a
deterministic template. The model can phrase; it cannot invent.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

_NUM = re.compile(r"\d+")
_LINE_REFS = [
    ("M", re.compile(r"\b(?:ligne|line|m[ée]tro|metro)\s?(\d{1,2}(?:\s?bis)?)\b", re.I)),
    ("RER", re.compile(r"\bRER\s?([A-E])\b", re.I)),
    ("T", re.compile(r"\b(?:tram(?:way)?\s?T?|T)(\d{1,2}[ab]?)\b", re.I)),
]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _line_codes(text: str) -> set[str]:
    folded = _fold(text)
    codes: set[str] = set()
    for kind, rx in _LINE_REFS:
        for m in rx.finditer(folded):
            codes.add(f"{kind}:{m.group(1).replace(' ', '').upper()}")
    return codes


def allowed_from(outputs: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    blob = json.dumps(outputs, ensure_ascii=False)
    numbers = set(_NUM.findall(blob))
    lines = _line_codes(blob)

    # Route legs carry bare codes ("B", "4", "T2") with a mode: turn them into refs too
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            code, mode = str(node.get("line", "")), str(node.get("mode", ""))
            if code and mode:
                kind = {"Metro": "M", "RapidTransit": "RER", "Tramway": "T"}.get(mode)
                if kind:
                    lines.add(f"{kind}:{code.upper().lstrip('T') if kind == 'T' else code.upper()}")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(outputs)
    return numbers, lines


def check(answer: str, outputs: list[dict[str, Any]]) -> list[str]:
    """Return a list of problems; empty means the answer is grounded."""
    numbers, lines = allowed_from(outputs)
    problems: list[str] = []
    for n in _NUM.findall(answer):
        if n not in numbers:
            problems.append(f"number {n} is not in the tool results")
    for code in _line_codes(answer):
        if code not in lines:
            problems.append(f"line {code.split(':', 1)[1]} is not in the tool results")
    return sorted(set(problems))
