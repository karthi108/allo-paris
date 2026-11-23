"""Phone test report: word error rate, completion and pairing with stored turns."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.phone_report import completed, load_calls, report, wer


def test_wer_folds_accents_and_counts_edits() -> None:
    assert wer("prochain métro ligne 4", "Prochain metro ligne 4") == 0.0
    assert wer("prochain métro ligne 4", "prochain métro ligne 14") == 0.25
    assert wer("a b c d", "a c d") == 0.25
    assert wer("", "") == 0.0


def test_completion_needs_an_expected_word_within_max_turns() -> None:
    task = {"must_any": ["minute"], "max_turns": 1}
    assert completed(task, ["Ligne 4 : dans 3 minutes."])
    assert not completed(task, ["Quelle ligne ?", "Dans 3 minutes."])


def test_report_pairs_calls_with_tasks_in_order() -> None:
    db = Path("data") / "_test_phone.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE calls (call_sid TEXT, caller_id TEXT, started_at TEXT);"
        "CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, call_sid TEXT, at TEXT, "
        "transcript TEXT, intent TEXT, answer TEXT, latency_ms INTEGER);"
        "INSERT INTO calls VALUES ('old', 'x', '2026-11-01T00:00');"
        "INSERT INTO calls VALUES ('c1', 'x', '2026-11-24T10:01');"
        "INSERT INTO turns (call_sid, at, transcript, intent, answer, latency_ms) VALUES "
        "('c1', 't', 'prochain métro ligne 4 à gare du nord', 'next_departure', "
        "'Ligne 4 direction Bagneux dans 2 minutes.', 120);"
    )
    con.commit()
    con.close()
    try:
        calls = load_calls(db, "2026-11-24T10:00")
        task = {
            "id": "P01",
            "goal": "g",
            "say": ["prochain métro ligne 4 à Gare du Nord"],
            "must_any": ["minute"],
            "max_turns": 2,
        }
        rep = report([task], calls, {"P01": True})
        assert rep["calls_found"] == 1
        assert rep["auto_completion"] == "1/1" and rep["owner_completion"] == "1/1"
        assert rep["mean_wer"] == 0.0 and rep["server_latency_p50_ms"] == 120
    finally:
        db.unlink()
