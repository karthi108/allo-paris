"""Turns a caller utterance into a spoken answer. All facts come from PRIM results.

Answers are built from fixed templates (docs/decisions.md D-001): the code only
inserts values taken from the data source, so it cannot invent a time.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.agent.agent import Agent, fallback_text
from app.agent.llm import LLMUnavailable
from app.agent.parser import ParsedQuery, parse
from app.core.metrics import Metrics
from app.data.prim import DeparturesResult, FeedError, TrafficResult
from app.data.stops import Line, StopArea, StopIndex, StopMatch, normalize
from app.data.velib import VelibResult
from app.ev.live import ChargerResult


class ChargerSource(Protocol):
    def nearby(
        self, lat: float, lon: float, radius_m: int = 500, limit: int = 3
    ) -> ChargerResult: ...
    def find_address(self, query: str) -> tuple[float, float, str] | None: ...


class BikeSource(Protocol):
    def nearby(
        self, lat: float, lon: float, radius_m: int = 500, limit: int = 3
    ) -> VelibResult: ...


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
    history: list[dict[str, str]] = field(default_factory=list)  # AI conversation turns
    ai_followup: bool = False  # the AI just asked a question; route the answer to it


T = {
    "fr": {
        "greeting": (
            "Bonjour, ici Allô Paris, un assistant vocal automatique et indépendant. "
            "Les horaires viennent des données temps réel officielles d'Île-de-France "
            "Mobilités. Service non affilié à IDFM ni à la RATP. "
            "For English, say English. "
            "Posez votre question, par exemple : prochain RER A à Châtelet."
        ),
        "again": "Autre question ? Sinon, raccrochez simplement.",
        "unsupported_route": "Je ne calcule pas encore les itinéraires. Je donne les prochains "
        "départs à une station : dites par exemple, RER A à Châtelet.",
        "unsupported_time": "Je donne uniquement les prochains départs en temps réel, pas les "
        "horaires futurs. Dites par exemple : ligne 4 à Gare du Nord.",
        "refused": "Je réponds uniquement aux questions sur les transports à Paris : horaires, "
        "perturbations, trajets et Vélib.",
        "unsupported_price": "Je ne donne pas les tarifs ni les titres de transport. Je réponds "
        "sur les horaires, les perturbations, les trajets et les Vélib.",
        "unsupported_bus": "Les bus ne sont pas encore couverts. Je réponds pour le métro, le "
        "RER, le tram et les trains.",
        "clarify_airport": "Quel aéroport : Orly ou Charles-de-Gaulle ?",
        "velib_which": "Vélib près de quelle station ? Par exemple : Vélib à Bastille.",
        "velib_none": "Aucune station Vélib à moins de 500 mètres de {stop}.",
        "velib_intro": "Vélib près de {stop}. ",
        "velib_station": "{name}, à {dist} mètres : {bikes} vélos dont {ebikes} électriques, "
        "{docks} places libres. ",
        "velib_closed": "{name}, à {dist} mètres : station fermée. ",
        "velib_fresh": "Données Vélib en temps réel.",
        "velib_old": "Attention, certaines stations n'ont pas mis à jour depuis {mins} minutes.",
        "velib_down": "Les données Vélib ne sont pas disponibles pour le moment.",
        "ev_which": "Bornes Belib' près de quel endroit ? Par exemple : bornes à Bastille.",
        "ev_none": "Aucune borne Belib' à moins de 500 mètres de {place}.",
        "ev_intro": "Bornes Belib' près de {place}. ",
        "ev_address": "{name}, à {dist} mètres : {available} libre(s) sur {total}",
        "ev_address_here": "{name}, sur place : {available} libre(s) sur {total}",
        "ev_out": ", {out} hors service",
        "ev_flagged": ". Attention : {n} borne(s) signalée(s) peu fiable(s) d'après l'historique",
        "ev_fresh": "Données Belib' en temps réel.",
        "ev_down": "Les données Belib' ne sont pas disponibles pour le moment.",
        "not_understood": "Je n'ai pas compris. Dites par exemple : ligne 4 à Gare du Nord.",
        "which_stop": "À quelle station ?",
        "which_stop_choice": "Vous voulez dire {a} ou {b} ?",
        "stop_not_found": "Je ne trouve pas de station dans votre question. Donnez un nom de "
        "station, par exemple : Bir-Hakeim, ou ligne 4 à Gare du Nord.",
        "landmark": "Station la plus proche {place} : {stop}. ",
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
        "unsupported_route": "I don't plan journeys yet. I give the next departures at a "
        "station: say for example, RER A at Châtelet.",
        "unsupported_time": "I only give the next real-time departures, not future timetables. "
        "Say for example: line 4 at Gare du Nord.",
        "refused": "I only answer Paris transport questions: departures, disruptions, routes "
        "and Vélib'.",
        "unsupported_price": "I don't give fares or ticket prices. I answer about departures, "
        "disruptions, routes and Vélib'.",
        "unsupported_bus": "Buses aren't covered yet. I answer for metro, RER, tram and trains.",
        "clarify_airport": "Which airport: Orly or Charles de Gaulle?",
        "velib_which": "Vélib near which station? For example: Vélib at Bastille.",
        "velib_none": "No Vélib station within 500 metres of {stop}.",
        "velib_intro": "Vélib near {stop}. ",
        "velib_station": "{name}, {dist} metres away: {bikes} bikes including {ebikes} "
        "electric, {docks} free docks. ",
        "velib_closed": "{name}, {dist} metres away: station closed. ",
        "velib_fresh": "Real-time Vélib data.",
        "velib_old": "Note: some stations haven't reported for {mins} minutes.",
        "velib_down": "Vélib data is unavailable right now.",
        "ev_which": "Belib' chargers near which place? For example: chargers at Bastille.",
        "ev_none": "No Belib' charger within 500 metres of {place}.",
        "ev_intro": "Belib' chargers near {place}. ",
        "ev_address": "{name}, {dist} metres away: {available} free out of {total}",
        "ev_address_here": "{name}, right here: {available} free out of {total}",
        "ev_out": ", {out} out of service",
        "ev_flagged": ". Note: {n} point(s) here flagged as unreliable from their history",
        "ev_fresh": "Real-time Belib' data.",
        "ev_down": "Belib' data is unavailable right now.",
        "not_understood": "Sorry, I didn't catch that. Say for example: line 4 at Gare du Nord.",
        "which_stop": "Which station?",
        "which_stop_choice": "Do you mean {a} or {b}?",
        "stop_not_found": "I can't find a station in your question. Give a station name, "
        "for example: Bir-Hakeim, or line 4 at Gare du Nord.",
        "landmark": "Nearest station to {place}: {stop}. ",
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


_PLACE_EN = {
    "la tour Eiffel": "the Eiffel Tower",
    "le Louvre": "the Louvre",
    "l'Arc de Triomphe": "the Arc de Triomphe",
    "le Sacré-Cœur": "Sacré-Cœur",
    "les Champs-Élysées": "the Champs-Élysées",
    "le château de Versailles": "the Palace of Versailles",
    "le Stade de France": "the Stade de France",
    "l'aéroport d'Orly": "Orly airport",
    "l'aéroport Charles-de-Gaulle": "Charles de Gaulle airport",
    "le Centre Pompidou": "the Centre Pompidou",
    "le musée d'Orsay": "the Musée d'Orsay",
}
_PLACE_FR = {v: k for k, v in _PLACE_EN.items()}


def _place(landmark: str, lang: str) -> str:
    if lang == "fr":
        return _de(_PLACE_FR.get(landmark, landmark))
    return _PLACE_EN.get(landmark, landmark)


def _de(place: str) -> str:
    """French 'de' + article: de le Louvre -> du Louvre, de les -> des."""
    for art, out in (("le ", "du "), ("les ", "des "), ("la ", "de la "), ("l'", "de l'")):
        if place.startswith(art):
            return out + place[len(art) :]
    return "de " + place


def _cap(text: str) -> str:
    """Uppercase the first letter only (str.capitalize would turn 'RER A' into 'Rer a')."""
    return text[:1].upper() + text[1:]


def _lines_list(lines: list[Line], lang: str) -> str:
    return ", ".join(ln.spoken(lang) for ln in lines[:8])


def _format_minutes(at: datetime, now: datetime, lang: str) -> str:
    mins = int((at - now).total_seconds() // 60)
    if mins <= 0:
        return t(lang, "now")
    if mins == 1:
        return t(lang, "one_minute")
    return t(lang, "minutes", n=mins)


def drop_terminating(result: DeparturesResult, stop: StopArea) -> DeparturesResult:
    """Remove trains whose destination is this station: they arrive and end here, so they
    are not departures (seen live: RER B at Gare du Nord -> "Paris Gare du Nord")."""
    here = normalize(stop.name)
    kept = [d for d in result.departures if normalize(d.destination) not in (here, f"paris {here}")]
    return DeparturesResult(kept, result.fetched_at)


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


def render_velib(result: VelibResult, stop: StopArea, lang: str) -> str:
    if not result.stations:
        return t(lang, "velib_none", stop=stop.name)
    parts = [t(lang, "velib_intro", stop=stop.name)]
    oldest = 0
    for s in result.stations[:3]:
        if not s.renting:
            parts.append(t(lang, "velib_closed", name=s.name, dist=s.distance_m))
            continue
        parts.append(
            t(
                lang,
                "velib_station",
                name=s.name,
                dist=s.distance_m,
                bikes=s.bikes,
                ebikes=s.ebikes,
                docks=s.docks,
            )
        )
        if s.reported_at:
            oldest = max(oldest, int((result.fetched_at - s.reported_at).total_seconds() // 60))
    parts.append(t(lang, "velib_old", mins=oldest) if oldest > 30 else t(lang, "velib_fresh"))
    return "".join(parts).strip()


def render_chargers(result: ChargerResult, place: str, lang: str) -> str:
    if not result.addresses:
        return t(lang, "ev_none", place=place)
    parts = [t(lang, "ev_intro", place=place)]
    for a in result.addresses[:3]:
        text = t(
            lang,
            "ev_address_here" if a.distance_m < 30 else "ev_address",
            name=a.name,
            dist=a.distance_m,
            available=a.available,
            total=a.in_service,
        )
        if a.out_of_service:
            text += t(lang, "ev_out", out=a.out_of_service)
        if a.flags:
            text += t(lang, "ev_flagged", n=len(a.flags))
        parts.append(text + ". ")
    parts.append(t(lang, "ev_fresh"))
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
    path: str = "rules"  # rules | ai | ai_fallback | rules_fallback
    grounded: bool = True  # every number/line in the text came from a data source
    latency_ms: int = 0
    tools: list[str] = field(default_factory=list)


# Rule outcomes the AI agent may improve on (when an LLM is configured)
AI_INTENTS = {"unknown", "unsupported_route", "unsupported_time"}


def _needs_ai(reply: Reply, utterance: str) -> bool:
    """Escalate when rules could not answer, or could only ask back about a long natural
    sentence (short replies to a clarifying question stay on the free rules path)."""
    if reply.intent in AI_INTENTS:
        return True
    long_sentence = len(utterance.split()) >= 6
    return long_sentence and reply.intent in ("clarify_line", "clarify_stop", "line_unknown")


def _mark(reply: Reply, path: str) -> Reply:
    reply.path = path
    return reply


class Dialog:
    def __init__(
        self,
        index: StopIndex,
        source: TransitSource,
        stale_after: int = 120,
        bikes: BikeSource | None = None,
        agent: Agent | None = None,
        metrics: Metrics | None = None,
        chargers: ChargerSource | None = None,
    ) -> None:
        self.index = index
        self.source = source
        self.stale_after = stale_after
        self.bikes = bikes
        self.agent = agent
        self.metrics = metrics or Metrics()
        self.chargers = chargers

    def handle(self, utterance: str, state: CallState) -> Reply:
        """Hybrid: rules first (free, fast, deterministic); the AI agent only for what
        rules cannot answer, or to continue a conversation the AI started."""
        t0 = time.perf_counter()
        reply: Reply | None = None
        if self.agent is not None and state.ai_followup:
            reply = self._try_agent(utterance, state)
        if reply is None:
            reply = self._handle_rules(utterance, state)
            if self.agent is not None and _needs_ai(reply, utterance):
                reply = self._try_agent(utterance, state) or _mark(reply, "rules_fallback")
        reply.latency_ms = int((time.perf_counter() - t0) * 1000)
        self.metrics.record(reply.path, reply.intent, reply.latency_ms)
        return reply

    def _try_agent(self, utterance: str, state: CallState) -> Reply | None:
        if self.agent is None:
            return None
        try:
            r = self.agent.run(utterance, state.lang, state.history)
        except LLMUnavailable:
            state.ai_followup = False
            return None
        text = r.text.strip() or fallback_text(r.tool_outputs, state.lang)
        state.history = (
            state.history
            + [{"role": "user", "content": utterance[:500]}, {"role": "assistant", "content": text}]
        )[-8:]
        state.ai_followup = text.endswith("?")
        stop = None
        for out in r.tool_outputs:
            if out.get("stations"):
                stop = self.index.by_id.get(out["stations"][0].get("station_id", ""))
                break
        if r.retried:
            self.metrics.guard_retries += 1
        if r.fallback:
            self.metrics.guard_fallbacks += 1
        return Reply(
            text,
            "ai",
            stop=stop,
            path="ai" if r.fallback is None else "ai_fallback",
            grounded=True,  # either passed the guard or replaced by a template
            tools=r.tools,
        )

    def _handle_rules(self, utterance: str, state: CallState) -> Reply:
        q = parse(utterance, self.index)
        if q.wants_english:
            state.lang = "en"
            return Reply(t("en", "switched"), "switch_language")
        lang = state.lang

        # Follow-up to a clarifying question
        if state.pending_stop and q.line and not q.stops:
            target = self.index.area_for_line(state.pending_stop, q.line) or state.pending_stop
            q.stops = [StopMatch(target, 1.0)]
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
        if q.intent in (
            "unsupported_route",
            "unsupported_time",
            "unsupported_bus",
            "unsupported_price",
            "refused",
        ):
            return Reply(t(lang, q.intent), q.intent)
        if q.intent == "clarify_airport":
            return Reply(t(lang, "clarify_airport"), "clarify_stop")
        if q.intent == "velib":
            reply = self._velib(q, lang)
            if q.landmark and reply.stop:
                place = _place(q.landmark, lang)
                reply.text = t(lang, "landmark", place=place, stop=reply.stop.name) + reply.text
            return reply
        if q.intent == "ev":
            return self._ev(q, utterance, lang)
        if q.intent == "unknown":
            return self._miss(state)
        reply = self._departures(q, state)
        if q.landmark and reply.stop:
            place = _place(q.landmark, lang)
            reply.text = t(lang, "landmark", place=place, stop=reply.stop.name) + reply.text
        return reply

    def _velib(self, q: ParsedQuery, lang: str) -> Reply:
        if not q.stops:
            return Reply(t(lang, "velib_which"), "clarify_stop")
        stop = q.stops[0].area
        if self.bikes is None or stop.lat is None or stop.lon is None:
            return Reply(t(lang, "velib_down"), "feed_down", stop=stop)
        try:
            result = self.bikes.nearby(stop.lat, stop.lon)
        except FeedError:
            return Reply(t(lang, "velib_down"), "feed_down", stop=stop)
        return Reply(render_velib(result, stop, lang), "velib", stop=stop)

    def _ev(self, q: ParsedQuery, utterance: str, lang: str) -> Reply:
        if self.chargers is None:
            return Reply(t(lang, "ev_down"), "feed_down")
        try:
            if q.stops and q.stops[0].score >= 0.9 and q.stops[0].area.lat is not None:
                stop = q.stops[0].area
                place = _place(q.landmark, lang) if q.landmark else stop.name
                lat, lon = stop.lat, stop.lon
            else:
                found = self.chargers.find_address(utterance)
                if found is None:
                    return Reply(t(lang, "ev_which"), "clarify_stop")
                lat, lon, place = found
            if lat is None or lon is None:
                return Reply(t(lang, "ev_which"), "clarify_stop")
            result = self.chargers.nearby(lat, lon)
        except FeedError:
            return Reply(t(lang, "ev_down"), "feed_down")
        return Reply(render_chargers(result, place, lang), "ev")

    def _miss(self, state: CallState) -> Reply:
        state.misses += 1
        return Reply(t(state.lang, "not_understood"), "unknown")

    def _departures(self, q: ParsedQuery, state: CallState) -> Reply:
        lang = state.lang
        if not q.stops:
            if q.line:
                state.pending_line = q.line
                return Reply(t(lang, "which_stop"), "clarify_stop")
            state.misses += 1
            return Reply(t(lang, "stop_not_found"), "unknown")
        if q.stop_ambiguous and q.stops[0].area.name != q.stops[1].area.name:
            if q.line:
                state.pending_line = q.line
            return Reply(
                t(lang, "which_stop_choice", a=q.stops[0].area.name, b=q.stops[1].area.name),
                "clarify_stop",
            )
        stop = q.stops[0].area
        line = q.line
        station_lines = self.index.station_lines(stop)  # metro + RER areas of one station
        if line is None:
            if len(station_lines) == 1:
                line = station_lines[0]
            else:
                state.pending_stop = stop
                return Reply(
                    t(lang, "which_line", stop=stop.name, lines=_lines_list(station_lines, lang)),
                    "clarify_line",
                    stop=stop,
                )
        served = self.index.area_for_line(stop, line)
        if served is None:
            return Reply(
                t(
                    lang,
                    "line_not_at_stop",
                    line=_cap(line.with_article(lang)),
                    stop=stop.name,
                    lines=_lines_list(station_lines, lang),
                ),
                "clarify_line",
            )
        stop = served
        try:
            result = self.source.next_departures(stop.monitoring_ref, line.line_id)
        except FeedError:
            return Reply(t(lang, "feed_down"), "feed_down")
        result = drop_terminating(result, stop)
        text = render_departures(result, line, stop, lang, datetime.now(UTC), self.stale_after)
        return Reply(text, "next_departure", stop=stop, line=line)

    def _traffic(self, line: Line, lang: str) -> Reply:
        try:
            result = self.source.traffic(line.line_id)
        except FeedError:
            return Reply(t(lang, "feed_down"), "feed_down")
        return Reply(render_traffic(result, line, lang), "line_status", line=line)
