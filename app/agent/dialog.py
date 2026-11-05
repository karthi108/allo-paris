"""Turns a caller utterance into a spoken answer. All facts come from PRIM results.

Answers are built from fixed templates (docs/decisions.md D-001): the code only
inserts values taken from the data source, so it cannot invent a time.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.agent.parser import ParsedQuery, parse
from app.data.prim import DeparturesResult, FeedError, TrafficResult
from app.data.stops import Line, StopArea, StopIndex


class TransitSource(Protocol):
    def next_departures(self, monitoring_ref: str, line_id: str | None) -> DeparturesResult: ...
    def traffic(self, line_id: str) -> TrafficResult: ...


@dataclass
class CallState:
    lang: str = "fr"
    pending_stop: StopArea | None = None  # asked "which line?" for this stop
    pending_line: Line | None = None  # asked "which station?" for this line
    misses: int = 0
    log: list[dict[str, str]] = field(default_factory=list)


T = {
    "fr": {
        "greeting": (
            "Bonjour, ici Allô Paris, un assistant vocal automatique, non officiel, "
            "basé sur les données temps réel d'Île-de-France Mobilités. "
            "For English, say English. "
            "Posez votre question, par exemple : prochain RER A à Châtelet."
        ),
        "again": "Autre question ? Sinon, raccrochez simplement.",
        "not_understood": "Je n'ai pas compris. Dites par exemple : ligne 4 à Gare du Nord.",
        "which_stop": "À quelle station ?",
        "which_stop_choice": "Vous voulez dire {a} ou {b} ?",
        "stop_not_found": "Je ne trouve pas cette station. Pouvez-vous répéter le nom ?",
        "line_unknown": "Je ne connais pas cette ligne. Dites par exemple RER B ou ligne 13.",
        "which_line": "À {stop}, quelle ligne ? {lines}.",
        "line_not_at_stop": "{line} ne passe pas à {stop}. Lignes disponibles : {lines}.",
        "no_departures": "Je n'ai pas de prochain départ pour {line} à {stop} en ce moment.",
        "departures_intro": "{line} à {stop}. ",
        "direction": "Direction {dest} : {times}. ",
        "minutes": "{n} minutes",
        "one_minute": "1 minute",
        "now": "moins d'une minute",
        "and": " puis ",
        "realtime": "Données temps réel, mises à jour il y a {age} secondes.",
        "scheduled": "Attention, ce sont des horaires théoriques, pas du temps réel.",
        "feed_down": (
            "Les données temps réel ne sont pas disponibles pour le moment. "
            "Je ne peux pas vous donner d'horaire fiable."
        ),
        "status_ok": "Aucun message de perturbation pour {line} en ce moment.",
        "status_msgs": "Pour {line} : {msgs}",
        "status_which_line": "Pour quelle ligne ? Par exemple RER A ou ligne 13.",
        "limit": "Le service a atteint sa limite d'appels pour aujourd'hui. Merci, au revoir.",
        "time_up": "Le temps d'appel maximum est atteint. Merci, au revoir.",
        "bye": "Merci d'avoir appelé Allô Paris. Au revoir.",
        "switched": "Je continue en français.",
    },
    "en": {
        "greeting": "",
        "again": "Any other question? Otherwise, just hang up.",
        "not_understood": "Sorry, I didn't catch that. Say for example: line 4 at Gare du Nord.",
        "which_stop": "Which station?",
        "which_stop_choice": "Do you mean {a} or {b}?",
        "stop_not_found": "I can't find that station. Could you say the name again?",
        "line_unknown": "I don't know that line. Say for example RER B or line 13.",
        "which_line": "At {stop}, which line? {lines}.",
        "line_not_at_stop": "{line} doesn't stop at {stop}. Available lines: {lines}.",
        "no_departures": "I have no upcoming departure for {line} at {stop} right now.",
        "departures_intro": "{line} at {stop}. ",
        "direction": "Towards {dest}: {times}. ",
        "minutes": "{n} minutes",
        "one_minute": "1 minute",
        "now": "under a minute",
        "and": ", then ",
        "realtime": "Real-time data, updated {age} seconds ago.",
        "scheduled": "Note: these are scheduled times, not real-time.",
        "feed_down": (
            "Real-time data is unavailable right now, so I can't give you a reliable time."
        ),
        "status_ok": "No disruption messages for {line} right now.",
        "status_msgs": "For {line}: {msgs}",
        "status_which_line": "Which line? For example RER A or line 13.",
        "limit": "The service has reached its call limit for today. Thank you, goodbye.",
        "time_up": "The maximum call time has been reached. Thank you, goodbye.",
        "bye": "Thanks for calling Allô Paris. Goodbye.",
        "switched": "Okay, continuing in English. Ask your question, for example: "
        "next RER A at Châtelet.",
    },
}


def t(lang: str, key: str, **kw: object) -> str:
    return T[lang][key].format(**kw)


def _cap(text: str) -> str:
    """Uppercase the first letter only (str.capitalize would turn 'RER A' into 'Rer a')."""
    return text[:1].upper() + text[1:]


def _lines_list(area: StopArea, lang: str) -> str:
    return ", ".join(ln.spoken(lang) for ln in area.lines[:8])


def _format_minutes(at: datetime, now: datetime, lang: str) -> str:
    mins = int((at - now).total_seconds() // 60)
    if mins <= 0:
        return t(lang, "now")
    if mins == 1:
        return t(lang, "one_minute")
    return t(lang, "minutes", n=mins)


def render_departures(
    result: DeparturesResult,
    line: Line,
    stop: StopArea,
    lang: str,
    now: datetime,
    stale_after: int,
) -> str:
    age = int((now - result.fetched_at).total_seconds())
    if age > stale_after:
        return t(lang, "feed_down")
    if not result.departures:
        return t(lang, "no_departures", line=line.with_article(lang), stop=stop.name)
    groups: OrderedDict[str, list[datetime]] = OrderedDict()
    for dep in result.departures:
        times = groups.setdefault(dep.destination, [])
        if len(times) < 2:
            times.append(dep.at)
    parts = [t(lang, "departures_intro", line=_cap(line.spoken(lang)), stop=stop.name)]
    for dest, times in list(groups.items())[:3]:
        spoken = T[lang]["and"].join(_format_minutes(a, now, lang) for a in times)
        parts.append(t(lang, "direction", dest=dest, times=spoken))
    shown = [d for d in result.departures if d.destination in list(groups)[:3]]
    if all(d.realtime for d in shown):
        parts.append(t(lang, "realtime", age=max(age, 0)))
    else:
        parts.append(t(lang, "scheduled"))
    return "".join(parts).strip()


def render_traffic(result: TrafficResult, line: Line, lang: str) -> str:
    if not result.messages:
        return t(lang, "status_ok", line=line.with_article(lang))
    msgs = " ".join(m.rstrip(".") + "." for m in result.messages[:2])
    if len(msgs) > 400:  # keep spoken answers short; cut at a sentence end
        cut = msgs.rfind(".", 0, 400)
        msgs = msgs[: cut + 1] if cut > 100 else msgs[:400].rstrip() + "…"
    return t(lang, "status_msgs", line=line.with_article(lang), msgs=msgs)


@dataclass
class Reply:
    text: str
    intent: str
    expect_more: bool = True  # keep listening after speaking
    stop: StopArea | None = None  # what the answer was about (web UI focuses the map)
    line: Line | None = None


class Dialog:
    def __init__(self, index: StopIndex, source: TransitSource, stale_after: int = 120) -> None:
        self.index = index
        self.source = source
        self.stale_after = stale_after

    def handle(self, utterance: str, state: CallState) -> Reply:
        q = parse(utterance, self.index)
        if q.wants_english:
            state.lang = "en"
            return Reply(t("en", "switched"), "switch_language")
        lang = state.lang

        # Follow-up to a clarifying question
        if state.pending_stop and q.line and not q.stops:
            q.stops = [
                s
                for s in self.index.match(state.pending_stop.name)
                if s.area.zda_id == state.pending_stop.zda_id
            ] or q.stops
        if state.pending_line and q.line is None and q.stops:
            q.line = state.pending_line
            q.intent = "next_departure"
        state.pending_stop = state.pending_line = None

        if q.line_heard:
            return Reply(t(lang, "line_unknown"), "clarify_line")
        if q.intent == "line_status":
            if not q.line:
                return Reply(t(lang, "status_which_line"), "clarify_line")
            return self._traffic(q.line, lang)
        if q.intent == "unknown":
            return self._miss(state)
        return self._departures(q, state)

    def _miss(self, state: CallState) -> Reply:
        state.misses += 1
        return Reply(t(state.lang, "not_understood"), "unknown")

    def _departures(self, q: ParsedQuery, state: CallState) -> Reply:
        lang = state.lang
        if not q.stops:
            if q.line:
                state.pending_line = q.line
                return Reply(t(lang, "which_stop"), "clarify_stop")
            return self._miss(state)
        if q.stop_ambiguous and q.stops[0].area.name != q.stops[1].area.name:
            if q.line:
                state.pending_line = q.line
            return Reply(
                t(lang, "which_stop_choice", a=q.stops[0].area.name, b=q.stops[1].area.name),
                "clarify_stop",
            )
        stop = q.stops[0].area
        line = q.line
        if line is None:
            if len(stop.lines) == 1:
                line = stop.lines[0]
            else:
                state.pending_stop = stop
                return Reply(
                    t(lang, "which_line", stop=stop.name, lines=_lines_list(stop, lang)),
                    "clarify_line",
                    stop=stop,
                )
        if line.line_id not in {ln.line_id for ln in stop.lines}:
            return Reply(
                t(
                    lang,
                    "line_not_at_stop",
                    line=_cap(line.with_article(lang)),
                    stop=stop.name,
                    lines=_lines_list(stop, lang),
                ),
                "clarify_line",
            )
        try:
            result = self.source.next_departures(stop.monitoring_ref, line.line_id)
        except FeedError:
            return Reply(t(lang, "feed_down"), "feed_down")
        text = render_departures(result, line, stop, lang, datetime.now(UTC), self.stale_after)
        return Reply(text, "next_departure", stop=stop, line=line)

    def _traffic(self, line: Line, lang: str) -> Reply:
        try:
            result = self.source.traffic(line.line_id)
        except FeedError:
            return Reply(t(lang, "feed_down"), "feed_down")
        return Reply(render_traffic(result, line, lang), "line_status", line=line)
