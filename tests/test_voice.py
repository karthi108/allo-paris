from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agent.dialog import Dialog
from app.core.store import Store
from app.data.stops import StopIndex
from app.voice import twiml
from app.voice.calls import CallConfig, CallHandler
from tests.conftest import FakeSource


def _handler(index: StopIndex, source: FakeSource, **kw: int) -> CallHandler:
    cfg = CallConfig(
        hmac_key=b"k" * 32,
        daily_call_cap=kw.get("cap", 100),
        per_caller_calls_per_day=kw.get("per_caller", 5),
        max_call_seconds=kw.get("max_s", 180),
    )
    return CallHandler(Dialog(index, source), Store(Path(":memory:"), 30), cfg)


def test_greeting_discloses_ai_and_listens(index: StopIndex, source: FakeSource) -> None:
    xml = _handler(index, source).incoming({"CallSid": "CA1", "From": "+33612345678"})
    assert "assistant vocal automatique" in xml and "non officiel" in xml
    assert '<Gather input="speech"' in xml and 'language="fr-FR"' in xml


def test_full_turn(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source)
    h.incoming({"CallSid": "CA1", "From": "+33612345678"})
    xml = h.speech({"CallSid": "CA1", "SpeechResult": "ligne 4 Château Rouge"})
    assert "Bagneux" in xml and "Autre question" in xml
    assert h.store.stats()["calls"] == 1


def test_raw_number_never_stored(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source)
    h.incoming({"CallSid": "CA1", "From": "+33612345678"})
    dump = "\n".join(h.store._db.iterdump())
    assert "612345678" not in dump


def test_per_caller_limit(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source, per_caller=2)
    for i in range(2):
        assert "<Gather" in h.incoming({"CallSid": f"CA{i}", "From": "+33612345678"})
    blocked = h.incoming({"CallSid": "CA9", "From": "+33612345678"})
    assert "<Hangup/>" in blocked and "limite" in blocked
    # another caller is still allowed
    assert "<Gather" in h.incoming({"CallSid": "CB1", "From": "+33700000000"})


def test_global_cap(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source, cap=1)
    h.incoming({"CallSid": "CA1", "From": "+33612345678"})
    assert "<Hangup/>" in h.incoming({"CallSid": "CA2", "From": "+33700000000"})


def test_max_call_duration(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source, max_s=60)
    h.store.start_call("CA1", "x", now=datetime.now(UTC) - timedelta(seconds=120))
    assert "<Hangup/>" in h.speech({"CallSid": "CA1", "SpeechResult": "ligne 4 Château Rouge"})


def test_hangs_up_after_repeated_misses(index: StopIndex, source: FakeSource) -> None:
    h = _handler(index, source)
    h.incoming({"CallSid": "CA1", "From": "+33612345678"})
    for _ in range(2):
        assert "<Gather" in h.speech({"CallSid": "CA1", "SpeechResult": ""})
    assert "<Hangup/>" in h.speech({"CallSid": "CA1", "SpeechResult": ""})


def test_transcripts_purged_after_retention() -> None:
    store = Store(Path(":memory:"), retention_days=30)
    old = datetime.now(UTC) - timedelta(days=31)
    store.log_turn("CA1", "old text", "x", "y", 5, now=old)
    store.log_turn("CA2", "new text", "x", "y", 5)
    rows = store._db.execute("SELECT transcript FROM turns").fetchall()
    assert rows == [("new text",)]


def test_xml_is_escaped() -> None:
    xml = twiml.gather("A & B <c>", "fr", "/voice/gather")
    assert "A &amp; B &lt;c&gt;" in xml


def test_signature_roundtrip_and_tamper() -> None:
    params = {"CallSid": "CA1", "From": "+33612345678", "SpeechResult": "ligne 4"}
    url = "https://example.ngrok-free.app/voice/gather"
    sig = twiml.twilio_signature("token", url, params)
    assert twiml.valid_signature("token", url, params, sig)
    assert not twiml.valid_signature("token", url, {**params, "SpeechResult": "x"}, sig)
    assert not twiml.valid_signature("", url, params, sig)
