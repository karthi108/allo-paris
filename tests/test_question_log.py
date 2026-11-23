"""Web question logging (step 5): text and time only, masked, deleted after 30 days,
and only when switched on. See /privacy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agent.dialog import Dialog
from app.api.web import WebApi
from app.core.store import Store, redact
from app.data.stops import StopIndex
from tests.conftest import FakeSource


def test_redact_masks_contact_details_but_keeps_transit_words() -> None:
    q = "appelez-moi au 06 12 34 56 78 ou jean.dupont@example.fr, ligne 14 à 7h30"
    out = redact(q)
    assert "06 12" not in out and "example.fr" not in out
    assert "[numéro]" in out and "[e-mail]" in out
    assert "ligne 14" in out and "7h30" in out


def test_store_keeps_only_text_and_time_and_deletes_after_30_days() -> None:
    store = Store(Path(":memory:"), retention_days=30)
    old = datetime(2026, 10, 1, tzinfo=UTC)
    store.log_question("prochain RER A à Nation", now=old)
    cols = [r[1] for r in store._db.execute("PRAGMA table_info(web_questions)")]
    assert cols == ["id", "at", "question"]  # no IP, no session, no answer
    assert store.web_questions() == [(old.isoformat(), "prochain RER A à Nation")]
    store.log_question("ligne 4 Gare du Nord", now=old + timedelta(days=31))
    assert [q for _, q in store.web_questions()] == ["ligne 4 Gare du Nord"]
    assert store.purge(now=old + timedelta(days=62)) == 1
    assert store.web_questions() == []


def test_ask_logs_the_question_text_only_when_switched_on(
    index: StopIndex, source: FakeSource
) -> None:
    seen: list[str] = []
    on = WebApi(index, Dialog(index, source), log_question=seen.append)
    on.ask("ligne 4 Château Rouge", "session-123")
    assert seen == ["ligne 4 Château Rouge"]  # the session id is never passed on
    off = WebApi(index, Dialog(index, source))
    assert off.log_question is None
    off.ask("ligne 4 Château Rouge", "s")


def test_a_logging_failure_never_breaks_the_answer(index: StopIndex, source: FakeSource) -> None:
    def broken(_: str) -> None:
        raise OSError("disk full")

    api = WebApi(index, Dialog(index, source), log_question=broken)
    assert api.ask("ligne 4 Château Rouge", "s")["intent"] == "next_departure"
