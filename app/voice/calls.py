"""Call flow for Twilio webhooks, framework-free so it can be unit tested.

POST /voice         -> new call: limits check, greeting, listen
POST /voice/gather  -> caller spoke: answer, listen again (or hang up)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agent.dialog import CallState, Dialog, t
from app.core.privacy import caller_id
from app.core.store import Store
from app.voice import twiml

log = logging.getLogger("allo.calls")

MAX_MISSES = 3
MAX_ACTIVE_STATES = 500


@dataclass
class CallConfig:
    hmac_key: bytes
    daily_call_cap: int
    per_caller_calls_per_day: int
    max_call_seconds: int
    voice_fr: str = ""
    voice_en: str = ""
    gather_path: str = "/voice/gather"


class CallHandler:
    def __init__(self, dialog: Dialog, store: Store, cfg: CallConfig) -> None:
        self.dialog = dialog
        self.store = store
        self.cfg = cfg
        self.states: dict[str, CallState] = {}

    def _voice(self, lang: str) -> str:
        return self.cfg.voice_fr if lang == "fr" else self.cfg.voice_en

    def incoming(self, params: dict[str, str]) -> str:
        sid = params.get("CallSid", "")
        try:
            cid = caller_id(params.get("From", ""), self.cfg.hmac_key)
        except ValueError:
            cid = "anonymous"  # withheld numbers share one bucket
        mine, total = self.store.counts_today(cid)
        if total >= self.cfg.daily_call_cap or mine >= self.cfg.per_caller_calls_per_day:
            log.warning("call rejected by limit total=%s mine=%s", total, mine)
            return twiml.hangup(t("fr", "limit"), "fr", self.cfg.voice_fr)
        self.store.start_call(sid, cid)
        if len(self.states) >= MAX_ACTIVE_STATES:  # bound memory: drop the oldest call state
            self.states.pop(next(iter(self.states)))
        self.states[sid] = CallState()
        return twiml.gather(t("fr", "greeting"), "fr", self.cfg.gather_path, self.cfg.voice_fr)

    def speech(self, params: dict[str, str]) -> str:
        sid = params.get("CallSid", "")
        state = self.states.setdefault(sid, CallState())
        lang = state.lang
        started = self.store.call_started_at(sid)
        if started and (datetime.now(UTC) - started).total_seconds() > self.cfg.max_call_seconds:
            self.states.pop(sid, None)
            return twiml.hangup(t(lang, "time_up"), lang, self._voice(lang))

        transcript = params.get("SpeechResult", "").strip()
        t0 = time.perf_counter()
        if not transcript:
            state.misses += 1
            reply_text, intent = t(lang, "not_understood"), "empty"
        else:
            reply = self.dialog.handle(transcript, state)
            reply_text, intent = reply.text, reply.intent
            if intent != "unknown":
                state.misses = 0
        latency_ms = int((time.perf_counter() - t0) * 1000)
        lang = state.lang
        self.store.log_turn(sid, transcript, intent, reply_text, latency_ms)
        log.info("turn intent=%s latency_ms=%s", intent, latency_ms)

        if state.misses >= MAX_MISSES:
            self.states.pop(sid, None)
            return twiml.hangup(t(lang, "bye"), lang, self._voice(lang))
        clarifying = intent.startswith("clarify") or intent in {
            "unknown",
            "empty",
            "switch_language",
        }
        text = reply_text if clarifying else f"{reply_text} {t(lang, 'again')}"
        return twiml.gather(text, lang, self.cfg.gather_path, self._voice(lang))
