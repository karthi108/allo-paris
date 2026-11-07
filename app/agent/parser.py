"""Deterministic question parser (v1, no LLM). See docs/decisions.md D-009.

Extracts: intent, line (mode + short name), stop area. Never invents data:
if something is missing or ambiguous, the result says so and the dialog asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.data.stops import Line, StopIndex, StopMatch, _best_window_score, normalize, tokens

# Well-known places -> nearest station name (matched fuzzily, so typos like "effile tower" work).
# Targets are resolved against IDFM stop names at query time; unknown targets are ignored.
LANDMARKS: dict[str, tuple[str, str]] = {
    "tour eiffel": ("la tour Eiffel", "Bir-Hakeim"),
    "eiffel tower": ("the Eiffel Tower", "Bir-Hakeim"),
    "louvre": ("le Louvre", "Palais Royal - Musée du Louvre"),
    "notre dame": ("Notre-Dame", "Saint-Michel Notre-Dame"),
    "arc de triomphe": ("l'Arc de Triomphe", "Charles de Gaulle - Étoile"),
    "sacre coeur": ("le Sacré-Cœur", "Anvers"),
    "montmartre": ("Montmartre", "Abbesses"),
    "champs elysees": ("les Champs-Élysées", "Franklin D. Roosevelt"),
    "disneyland": ("Disneyland Paris", "Marne-la-Vallée - Chessy"),
    "versailles chateau": ("le château de Versailles", "Versailles Château Rive Gauche"),
    "chateau de versailles": ("le château de Versailles", "Versailles Château Rive Gauche"),
    "stade de france": ("le Stade de France", "Stade de France Saint-Denis"),
    "orly": ("l'aéroport d'Orly", "Aéroport d'Orly"),
    "roissy": ("l'aéroport Charles-de-Gaulle", "Aéroport Charles de Gaulle 2 (Terminal 2)"),
    "cdg": ("l'aéroport Charles-de-Gaulle", "Aéroport Charles de Gaulle 2 (Terminal 2)"),
    "beaubourg": ("le Centre Pompidou", "Rambuteau"),
    "pompidou": ("le Centre Pompidou", "Rambuteau"),
    "musee d orsay": ("le musée d'Orsay", "Musée d'Orsay"),
}


def _landmark(text: str) -> tuple[str, str, float] | None:
    """Return (spoken place, station name, match score) for the best landmark, if any."""
    words = tokens(text)
    best: tuple[float, tuple[str, str]] | None = None
    for key, value in LANDMARKS.items():
        score = _best_window_score(words, tokens(key))
        if score >= 0.8 and (best is None or score > best[0]):
            best = (score, value)
    return (best[1][0], best[1][1], best[0]) if best else None


_STATUS_WORDS = re.compile(
    r"\b(perturbation|perturbations|trafic|traffic|incident|incidents|probleme|problemes|"
    r"panne|greve|retard|retards|travaux|disruption|disruptions|delay|delays|status|statut|"
    r"fonctionne|marche|working|running|info|infos|broken|down|cancelled|canceled|annule|"
    r"annulee|bloque|bloquee|ferme|fermee|closed|issue|issues|problem|problems|greves|strike)\b"
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
    # How Parisians say it: "la 13", "le 4". Only accepted if it is a real metro line.
    ("MetroBare", re.compile(r"\b(?:la|le)\s(\d{1,2}(?:\s?bis)?)\b")),
]

# Questions v1 cannot answer honestly: say so instead of guessing.
_ROUTE = re.compile(
    r"\b(comment (aller|me rendre|je vais|on va|faire pour aller)|itineraire|trajet|"
    r"(je veux|je voudrais|j aimerais|je dois|on veut) (aller|me rendre)|pour aller a|"
    r"chemin le plus (rapide|court)|meilleur chemin|le plus rapide pour|"
    r"how (do i|to|can i|should i) (get|go)|(i want|i d like|i need|we want) to (go|get)|"
    r"directions?|fastest (way|route)|quickest (way|route)|best (way|route)|get to)\b"
)
# Origin and destination both given, either order (normalized text): "from Nation to Bastille",
# "de Nation à Bastille", "to the Louvre from Gare de Lyon", "à Bastille en partant de Nation".
# Only used when no line is named: "RER A vers La Défense depuis Nation" stays a departure question.
FROM_TO = re.compile(
    r"\b(from|de|depuis|en partant de) \w.* (to|a|au|vers|pour|jusqu a) \w"
    r"|\b(to|a|au) \w.* (from|depuis|en partant de) \w"
)
_FUTURE = re.compile(
    r"\b(demain|tomorrow|ce soir|tonight|apres demain|lundi|mardi|mercredi|jeudi|vendredi|"
    r"samedi|dimanche|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{1,2} ?h(?: ?\d\d)?|\d{1,2} ?(?:am|pm)|\d{1,2} \d\d)\b"
)
_VELIB = re.compile(r"\b(velib|velibs|velo|velos|bike|bikes|bicycle|bicycles|cycle)\b")
# Prompt-injection phrasing: refused deterministically, never sent to the LLM or data APIs
_INJECTION = re.compile(
    r"\b(ignore (all |your |the |any )?(previous |prior |above )?(instructions|rules|prompt)|"
    r"developer mode|system prompt|jailbreak|you are now|act as|pretend (to be|you are)|"
    r"oublie (tes|les|toutes les) (instructions|regles|consignes)|mode developpeur)\b"
)
_PRICE = re.compile(
    r"\b(prix|tarif|tarifs|ticket|tickets|billet|billets|navigo|combien (coute|ca coute)|"
    r"how much|price|prices|fare|fares|cost)\b"
)
_BUS = re.compile(r"\b(bus|autobus|noctilien)\b")
_AIRPORT = re.compile(r"\b(aeroport|airport)\b")
_AIRPORT_NAMED = re.compile(r"\b(orly|roissy|cdg|charles de gaulle|beauvais)\b")


@dataclass
class ParsedQuery:
    intent: str  # next_departure | line_status | unknown
    line: Line | None = None
    line_heard: str | None = None  # line mentioned but not found in reference data
    stops: list[StopMatch] = field(default_factory=list)
    wants_english: bool = False
    landmark: str | None = None  # e.g. "la tour Eiffel" when the stop came from a landmark

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
        if mode == "MetroBare":
            bare = index.find_line("Metro", short)
            if bare is None:
                continue  # "le 21 novembre" is a date, not a line
            stripped = (text[: m.start()] + " " + text[m.end() :]).strip()
            return bare, None, stripped
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
    if _INJECTION.search(text):
        return ParsedQuery("refused")
    if _ROUTE.search(text):
        return ParsedQuery("unsupported_route")
    if _PRICE.search(text):
        return ParsedQuery("unsupported_price")
    if _BUS.search(text):
        return ParsedQuery("unsupported_bus")
    if _FUTURE.search(text) and not _STATUS_WORDS.search(text):
        return ParsedQuery("unsupported_time")  # disruption questions may mention dates
    if _AIRPORT.search(text) and not _AIRPORT_NAMED.search(text):
        return ParsedQuery("clarify_airport")
    if _VELIB.search(text):
        place = _VELIB.sub(" ", text)
        stops = index.match(place)
        landmark = None
        found = _landmark(place)
        if found and (not stops or stops[0].score < 0.95 or found[2] >= 0.95):
            near = index.match(found[1])
            if near and near[0].score >= 0.95:
                stops, landmark = near[:1], found[0]
        return ParsedQuery("velib", stops=stops, landmark=landmark)
    line, heard, rest = _extract_line(text, index)
    if line is None and heard is None and FROM_TO.search(text):
        # A trip between two places: rules cannot plan it (the AI can). Found in agent eval
        # run 2: "from Gare du Nord to Bir-Hakeim" was answered with line 6 departures.
        return ParsedQuery("unsupported_route")
    intent = "line_status" if _STATUS_WORDS.search(text) else "next_departure"
    if intent == "line_status":
        return ParsedQuery(intent, line=line, line_heard=heard)
    stops = index.match(rest, line=line) if rest else []
    if not stops and line is not None:
        # Line found but stop does not serve it: retry without the line filter
        stops = index.match(rest)
    landmark = None
    found = _landmark(rest) if rest else None
    # A landmark said exactly ("stade de france") wins over a partial station match
    if found and (not stops or stops[0].score < 0.95 or found[2] >= 0.95):
        near = index.match(found[1], line=line) or index.match(found[1])
        if near and near[0].score >= 0.95:
            stops, landmark = near[:1], found[0]
    if not stops and line is None and heard is None and not rest:
        return ParsedQuery("unknown")
    return ParsedQuery(intent, line=line, line_heard=heard, stops=stops, landmark=landmark)
