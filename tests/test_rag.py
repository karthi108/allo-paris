"""RAG v1 (D-025): BM25 over the licensed corpus, cited answers, accessibility coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.agent import Agent
from app.agent.dialog import CallState, Dialog
from app.agent.llm import LLMResponse
from app.agent.parser import parse
from app.agent.tools import Toolbox
from app.data.stops import StopIndex
from app.rag.corpus import Corpus, Doc, best_sentences, citation_text, cite_for, terms
from tests.conftest import FakeSource
from tests.test_agent import ScriptedLLM, call

ROOT = Path(__file__).resolve().parents[1]


def _doc(i: str, text: str, kind: str = "fiche", zda: str = "") -> Doc:
    return Doc(
        i, kind, f"title {i}", text, "Service Public / DILA", "LO 2.0", "u", "2026-07-21", zda
    )


def test_terms_fold_accents_stopwords_and_plurals() -> None:
    assert terms("Les Amendes reçues dans le métro") == ["amende", "recue", "metro"]


def test_bm25_ranks_the_matching_passage_and_ignores_unrelated() -> None:
    c = Corpus(
        [
            _doc("a", "Vous pouvez contester une amende reçue dans les transports en commun."),
            _doc("b", "La carte mobilité inclusion donne une place assise prioritaire."),
            _doc("c", "Le médiateur traite les litiges commerciaux."),
        ]
    )
    assert [d.id for d in c.search("contester mon amende", limit=2)] == ["a"]
    assert c.search("quel temps fera-t-il") == []
    assert [d.id for d in c.search("place assise", kind="fiche")] == ["b"]
    assert c.search("place assise", kind="accessibility") == []


def test_citation_has_source_and_date_in_brackets() -> None:
    assert citation_text("Service Public / DILA", "2026-07-21", "fr") == (
        "(Source : Service Public / DILA, mise à jour le 21/07/2026)"
    )
    assert citation_text("X", "2026-07-21", "en") == "(Source: X, updated 21/07/2026)"


def test_cite_for_picks_the_passage_the_answer_used() -> None:
    outputs = [
        {
            "_tool": "search_docs",
            "passages": [
                {
                    "passage": "Le médiateur SNCF traite les litiges.",
                    "source": "A",
                    "updated": "2026-01-02",
                },
                {
                    "passage": "Réclamation sous 3 mois au service clientèle.",
                    "source": "B",
                    "updated": "2026-03-04",
                },
            ],
        }
    ]
    assert cite_for("Envoyez une réclamation au service clientèle.", outputs, "fr").startswith(
        "(Source : B"
    )
    assert cite_for("anything", [{"_tool": "next_departures"}], "fr") == ""


def test_best_sentences_are_verbatim_and_in_order() -> None:
    text = "Premier point général. Le délai est de 3 mois pour la réclamation. Dernier point."
    assert (
        best_sentences(text, "délai réclamation", n=1)
        == "Le délai est de 3 mois pour la réclamation."
    )
    assert (
        best_sentences(text, "zzz", n=2)
        == "Premier point général. Le délai est de 3 mois pour la réclamation."
    )


# ---------- the committed corpus ----------


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return Corpus.load(ROOT / "data" / "docs.json")


@pytest.fixture(scope="module")
def full() -> StopIndex:
    return StopIndex.load(ROOT / "eval" / "data" / "stops_snapshot.json")


def test_committed_corpus_records_source_licence_and_date(corpus: Corpus) -> None:
    kinds = {d.kind for d in corpus.docs}
    assert kinds == {"accessibility", "fiche"}
    for d in corpus.docs:
        assert d.source and d.licence and d.url
        assert len(d.updated) == 10 and d.updated[4] == "-"  # YYYY-MM-DD
        assert "Licence Ouverte" in d.licence
    assert all(len(d.text) <= 1200 for d in corpus.docs if d.kind == "fiche")


@pytest.mark.parametrize(
    "q", ["Gare de Lyon accessible fauteuil ?", "is Saint-Michel Notre-Dame wheelchair accessible"]
)
def test_accessibility_answer_is_the_record_with_citation(
    corpus: Corpus, full: StopIndex, q: str
) -> None:
    reply = Dialog(full, FakeSource(), docs=corpus).handle(q, CallState())
    assert reply.intent == "accessibility"
    assert "(Source" in reply.text and "Île-de-France Mobilités" in reply.text
    assert "accessible" in reply.text


def test_metro_only_station_is_not_covered_never_guessed(corpus: Corpus, full: StopIndex) -> None:
    reply = Dialog(full, FakeSource(), docs=corpus).handle("ascenseur à Concorde ?", CallState())
    assert reply.intent == "accessibility"
    assert "pas le métro" in reply.text
    for level in ("non accessible", "sur demande", "sur réservation", "en toute autonomie"):
        assert level not in reply.text


def test_fine_amount_stays_a_price_refusal(full: StopIndex) -> None:
    assert parse("combien coûte une amende dans le RER", full).intent == "unsupported_price"
    assert parse("je veux contester mon amende du RER", full).intent == "docs"


def test_docs_question_without_ai_gets_a_cited_excerpt(corpus: Corpus, full: StopIndex) -> None:
    reply = Dialog(full, FakeSource(), docs=corpus).handle(
        "à quoi sert la carte mobilité inclusion priorité ?", CallState()
    )
    assert reply.intent == "docs" and "(Source : Service Public / DILA" in reply.text


def test_no_corpus_says_documents_are_unavailable(full: StopIndex) -> None:
    reply = Dialog(full, FakeSource()).handle("Gare de Lyon accessible fauteuil ?", CallState())
    assert "pas disponibles" in reply.text


def test_search_docs_tool_station_record_and_lines(corpus: Corpus, full: StopIndex) -> None:
    box = Toolbox(full, FakeSource(), docs=corpus)
    gdn = full.match("Gare du Nord", limit=1)[0].area.zda_id
    out = box._t_search_docs("accessibilité", station_id=gdn)
    assert out["passages"] and out["passages"][0]["source"].startswith("Île-de-France")
    assert any(x["line"] == "B" for x in out["lines_at_station"])  # lines for the guard
    bastille = full.match("Bastille", limit=1)[0].area.zda_id
    none = box._t_search_docs("accessibilité", station_id=bastille)
    assert none["passages"] == [] and "not metro" in none["note"]


def test_agent_answer_from_docs_gets_the_citation_appended(corpus: Corpus, full: StopIndex) -> None:
    llm = ScriptedLLM(
        [
            call("search_docs", query="contester amende transport"),
            LLMResponse(
                "Oui, vous pouvez contester un procès-verbal reçu dans les transports en commun.",
                [],
                100,
                20,
            ),
        ]
    )
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus))
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "je veux contester mon amende", CallState()
    )
    assert reply.path == "ai"
    assert reply.text.endswith("mise à jour le 21/07/2026)")
    assert "(Source : Service Public / DILA" in reply.text


def test_agent_cannot_invent_a_number_not_in_the_passage(corpus: Corpus, full: StopIndex) -> None:
    llm = ScriptedLLM(
        [
            call("search_docs", query="contester amende transport"),
            LLMResponse("Vous avez 6 mois pour contester.", [], 100, 20),
            LLMResponse("Vous avez 6 mois pour contester.", [], 100, 20),  # same after retry
        ]
    )
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus))
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "je veux contester mon amende", CallState()
    )
    assert reply.path == "ai_fallback"  # guard: 6 is not in the passage
    assert "6 mois" not in reply.text and "(Source" in reply.text
