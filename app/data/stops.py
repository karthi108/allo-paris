"""Stop areas, lines, and fuzzy stop matching against what the caller said."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

MODE_LABEL_FR = {"Metro": "métro", "RapidTransit": "RER", "Tramway": "tram", "LocalTrain": "train"}
MODE_LABEL_EN = {"Metro": "metro", "RapidTransit": "RER", "Tramway": "tram", "LocalTrain": "train"}

# Filler words removed before matching stop names
_STOPWORDS = {
    "le",
    "la",
    "les",
    "l",
    "de",
    "du",
    "des",
    "d",
    "a",
    "au",
    "aux",
    "et",
    "en",
    "the",
    "at",
    "station",
    "gare",
    "arret",
    "metro",
    "rer",
    "tram",
    "ligne",
    "line",
    "prochain",
    "prochains",
    "prochaine",
    "next",
    "train",
    "trains",
    "quand",
    "when",
    "is",
    "passe",
    "part",
    "pour",
    "from",
    "to",
    "direction",
    "vers",
    "je",
    "suis",
    "veux",
    "voudrais",
    "s",
    "il",
    "vous",
    "plait",
    "please",
    "what",
    "time",
    "heure",
    "quelle",
    "quel",
}


def normalize(text: str) -> str:
    """Lowercase, strip accents, turn punctuation and hyphens into spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"\bst\b", "saint", text)
    text = re.sub(r"\bste\b", "sainte", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in _STOPWORDS]


@dataclass(frozen=True)
class Line:
    line_id: str  # e.g. C01742
    short: str  # e.g. A, 4, T3a
    mode: str  # Metro, RapidTransit, Tramway, LocalTrain
    color: str = ""  # hex without #, from referentiel-des-lignes
    text_color: str = ""

    def spoken(self, lang: str) -> str:
        if self.mode == "Metro":
            return f"ligne {self.short}" if lang == "fr" else f"line {self.short}"
        if self.mode == "Tramway":
            return f"tram {self.short}"
        label = (MODE_LABEL_FR if lang == "fr" else MODE_LABEL_EN)[self.mode]
        return f"{label} {self.short}"

    def with_article(self, lang: str) -> str:
        """French needs the right article: la ligne 4, le RER A, le tram T2, le train H."""
        spoken = self.spoken(lang)
        if lang != "fr":
            return spoken
        return ("la " if self.mode == "Metro" else "le ") + spoken


@dataclass
class StopArea:
    zda_id: str
    name: str
    lines: list[Line] = field(default_factory=list)
    lat: float | None = None
    lon: float | None = None

    @property
    def monitoring_ref(self) -> str:
        return f"STIF:StopArea:SP:{self.zda_id}:"


def _float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def build_index_records(
    line_rows: list[dict[str, Any]],
    arr_rows: list[dict[str, Any]],
    colors: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Group arrets-lignes rows by stop area. Pure function, unit tested."""
    colors = colors or {}
    arr_to_zda = {str(r["arrid"]): str(r["zdaid"]) for r in arr_rows if r.get("zdaid")}
    areas: dict[str, dict[str, Any]] = {}
    for row in line_rows:
        stop_id = str(row.get("stop_id") or "")
        if stop_id.startswith("IDFM:monomodalStopPlace:"):
            zda = stop_id.rsplit(":", 1)[1]
        elif re.fullmatch(r"IDFM:\d+", stop_id):
            zda = arr_to_zda.get(stop_id.split(":")[1], "")
        else:
            zda = ""
        if not zda:
            continue
        area = areas.setdefault(
            zda,
            {
                "zda_id": zda,
                "name": row["stop_name"],
                "lat": _float(row.get("stop_lat")),
                "lon": _float(row.get("stop_lon")),
                "lines": {},
            },
        )
        if area["lat"] is None:
            area["lat"], area["lon"] = _float(row.get("stop_lat")), _float(row.get("stop_lon"))
        line_id = str(row["id"]).replace("IDFM:", "")
        color, text_color = colors.get(line_id, ("", ""))
        area["lines"][line_id] = {
            "line_id": line_id,
            "short": row["shortname"],
            "mode": row["mode"],
            "color": color,
            "text_color": text_color,
        }
    return [
        {**a, "lines": sorted(a["lines"].values(), key=lambda x: (x["mode"], x["short"]))}
        for a in sorted(areas.values(), key=lambda a: a["name"])
    ]


@dataclass(frozen=True)
class StopMatch:
    area: StopArea
    score: float


class StopIndex:
    def __init__(self, areas: list[StopArea]) -> None:
        self.areas = areas
        self._tokens = {a.zda_id: tokens(a.name) for a in areas}
        self.by_id = {a.zda_id: a for a in areas}
        self.lines: dict[tuple[str, str], Line] = {}
        for area in areas:
            for line in area.lines:
                self.lines[(line.mode, normalize(line.short))] = line

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> StopIndex:
        return cls(
            [
                StopArea(
                    r["zda_id"],
                    r["name"],
                    [Line(**ln) for ln in r["lines"]],
                    r.get("lat"),
                    r.get("lon"),
                )
                for r in records
            ]
        )

    @classmethod
    def load(cls, path: Path) -> StopIndex:
        return cls.from_records(json.loads(path.read_text(encoding="utf-8")))

    def find_line(self, mode: str | None, short: str) -> Line | None:
        key = normalize(short)
        if mode:
            return self.lines.get((mode, key))
        for m in ("Metro", "RapidTransit", "Tramway", "LocalTrain"):
            if (m, key) in self.lines:
                return self.lines[(m, key)]
        return None

    def match(self, utterance: str, line: Line | None = None, limit: int = 3) -> list[StopMatch]:
        """Score every stop name against windows of the utterance. Higher is better (0-1)."""
        words = tokens(utterance)
        if not words:
            return []
        results: list[StopMatch] = []
        for area in self.areas:
            if line and line.line_id not in {ln.line_id for ln in area.lines}:
                continue
            name_toks = self._tokens[area.zda_id]
            if not name_toks:
                continue
            score = _best_window_score(words, name_toks)
            if score >= 0.75:
                results.append(StopMatch(area, score))
        results.sort(key=lambda m: (-m.score, len(m.area.name)))
        return results[:limit]


_GENERIC_FIRST = {"saint", "sainte", "porte", "pont", "place", "rue", "avenue", "boulevard"}


def _tok_eq(a: str, b: str) -> bool:
    return a == b or (len(a) > 3 and SequenceMatcher(None, a, b).ratio() >= 0.85)


def _best_window_score(words: list[str], name_toks: list[str]) -> float:
    target = " ".join(name_toks)
    n = len(name_toks)
    best = 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(words) - size + 1)):
            window = " ".join(words[i : i + size])
            ratio = SequenceMatcher(None, window, target).ratio()
            # Partial name ("Chatelet" for "Chatelet Les Halles") is penalised slightly
            if size < n:
                ratio *= 0.92
            best = max(best, ratio)
    # Prefix match: caller said the first k words of a longer name
    # ("Saint-Michel" for "Saint-Michel Notre-Dame"). Scored below an exact match.
    for k in range(1, n):
        prefix = name_toks[:k]
        if k == 1 and (prefix[0] in _GENERIC_FIRST or len(prefix[0]) < 5):
            continue
        for i in range(0, len(words) - k + 1):
            if all(_tok_eq(w, p) for w, p in zip(words[i : i + k], prefix, strict=True)):
                best = max(best, 0.8 + 0.15 * k / n)
    return best
