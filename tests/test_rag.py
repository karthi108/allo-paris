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


# ---------- fixes after held-out set 4 (2026-11-23); wording differs from the eval ----------


@pytest.mark.parametrize(
    "q", ["c'est quoi le prochain RER à Juvisy", "est-ce que Vincennes est accessible ?"]
)
def test_bare_est_does_not_match_gare_de_l_est(full: StopIndex, q: str) -> None:
    # R1: "Gare de l'Est" reduces to "est"; "c'est" / "est-ce" must not match it
    assert all(m.area.name != "Gare de l'Est" for m in full.match(q))


@pytest.mark.parametrize("q", ["Gare de l'Est", "prochain métro 5 gare de l est"])
def test_full_name_still_matches_gare_de_l_est(full: StopIndex, q: str) -> None:
    assert full.match(q)[0].area.name == "Gare de l'Est"


def test_abbreviated_last_word_prefers_the_longer_name(full: StopIndex) -> None:
    # R2: "Cité U" is Cité Universitaire; "Cité" alone stays the metro station
    assert full.match("RER à cité u")[0].area.name == "Cité Universitaire"
    assert full.match("métro à cité")[0].area.name == "Cité"


def test_partial_name_accepted_only_when_unique(corpus: Corpus, full: StopIndex) -> None:
    # R3: "Juvisy" style partial names; "Massy" has several stations, so it asks
    dialog = Dialog(full, FakeSource(), docs=corpus)
    one = dialog.handle("Denfert PMR accessible", CallState())
    assert "Denfert-Rochereau" in one.text and "(Source" in one.text
    many = dialog.handle("Massy accessible PMR", CallState())
    assert many.intent == "clarify_stop"


@pytest.mark.parametrize(
    "q", ["puis-je monter avec mon vélo dans le tram ?", "bike allowed on the RER?"]
)
def test_bike_on_board_is_not_velib(full: StopIndex, q: str) -> None:
    # R4
    assert parse(q, full).intent != "velib"


@pytest.mark.parametrize("q", ["vélo près de Bastille", "Vélib à la gare RER de Nation"])
def test_bike_availability_stays_velib(full: StopIndex, q: str) -> None:
    assert parse(q, full).intent == "velib"


def test_search_needs_two_shared_words() -> None:
    # A3: one incidental shared word is not a match
    c = Corpus(
        [
            _doc("a", "Le médiateur de la RATP traite les litiges."),
            _doc("b", "La médiatrice de la SNCF rend un avis."),
        ]
    )
    assert c.search("loi grève RATP") == []
    assert [d.id for d in c.search("médiateur SNCF avis")] == ["b"]  # -trice read as -teur
    assert [d.id for d in c.search("RATP")] == ["a"]  # a one-word query needs that word


def test_search_docs_ranks_on_the_users_words_too(corpus: Corpus, full: StopIndex) -> None:
    # A2: the model's generic keywords plus the user's question pick the right section
    box = Toolbox(full, FakeSource(), docs=corpus)
    box.question = "qui décide d'attribuer la carte ?"
    out = box._t_search_docs("carte mobilité inclusion")
    assert len(out["passages"]) == 5
    assert "Qui décide" in out["passages"][0]["title"]


def test_facts_without_any_tool_are_replaced(corpus: Corpus, full: StopIndex) -> None:
    # A1: an answer with no tool call gets one retry, then the "no document" template
    llm = ScriptedLLM(
        [
            LLMResponse("Small parrots must travel in a closed cage.", [], 100, 20),
            LLMResponse("Small parrots must travel in a closed cage.", [], 100, 20),
        ]
    )
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus))
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "can I bring my parrot on the tram", CallState(lang="en")
    )
    assert reply.text == "I have no official document on this question."
    assert len(llm.sent) == 2  # the retry happened


def test_a_question_back_needs_no_tool(corpus: Corpus, full: StopIndex) -> None:
    llm = ScriptedLLM([LLMResponse("Which station do you mean?", [], 100, 20)])
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus))
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "hello, I have a question for you about something", CallState(lang="en")
    )
    assert reply.path == "ai"
    assert reply.text == "Which station do you mean?" and len(llm.sent) == 1


def test_no_fee_from_a_document(corpus: Corpus, full: StopIndex) -> None:
    # A5: a fee stated in a fiche is never repeated
    fee = "Demandez un duplicata en ligne. La refabrication coûte 10 €."
    llm = ScriptedLLM(
        [
            call("search_docs", query="perte carte mobilité inclusion duplicata"),
            LLMResponse(fee, [], 100, 20),
            LLMResponse(fee, [], 100, 20),
        ]
    )
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus))
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "j'ai égaré ma carte d'invalidité CMI", CallState()
    )
    assert "€" not in reply.text and "duplicata" in reply.text


# ---------- support check (after held-out set 5); wording differs from the eval ----------


def _parking_llm() -> ScriptedLLM:
    return ScriptedLLM(
        [
            call("search_docs", query="carte stationnement"),
            LLMResponse(
                "Pour la vignette de quartier, adressez-vous à votre mairie avec un justificatif.",
                [],
                100,
                20,
            ),
        ]
    )


def test_unsupported_document_answer_is_replaced_and_not_cited(
    corpus: Corpus, full: StopIndex
) -> None:
    seen: list[int] = []

    def verify(answer: str, passages: list[dict[str, object]]) -> bool:
        seen.append(len(passages))
        return False

    agent = Agent(_parking_llm(), lambda: Toolbox(full, FakeSource(), docs=corpus), verify=verify)
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "comment avoir la vignette de stationnement de mon quartier", CallState()
    )
    assert seen and seen[0] > 0
    assert "mairie" not in reply.text
    assert "(Source" not in reply.text
    assert "pas de document" in reply.text


def test_supported_document_answer_keeps_its_citation(corpus: Corpus, full: StopIndex) -> None:
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
    agent = Agent(llm, lambda: Toolbox(full, FakeSource(), docs=corpus), verify=lambda a, p: True)
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "je veux contester mon amende", CallState()
    )
    assert "(Source : Service Public / DILA" in reply.text


def test_support_check_unavailable_keeps_the_answer(corpus: Corpus, full: StopIndex) -> None:
    from app.agent.llm import LLMUnavailable

    def down(answer: str, passages: list[dict[str, object]]) -> bool:
        raise LLMUnavailable("budget")

    agent = Agent(_parking_llm(), lambda: Toolbox(full, FakeSource(), docs=corpus), verify=down)
    reply = Dialog(full, FakeSource(), agent=agent, docs=corpus).handle(
        "comment avoir la vignette de stationnement de mon quartier", CallState()
    )
    assert "mairie" in reply.text  # unchanged: the numbers-and-lines guard still applied


# ---------- town names containing a landmark word (live check 2026-11-23); new wording ----------


@pytest.mark.parametrize(
    ("q", "station"),
    [
        ("Roissy-en-Brie, ascenseur sur le quai ?", "Roissy-en-Brie"),
        ("is Orly Ville station step free", "Orly Ville"),
        ("prochain RER E à Roissy-en-Brie", "Roissy-en-Brie"),
    ],
)
def test_full_town_station_name_beats_the_airport_landmark(
    full: StopIndex, q: str, station: str
) -> None:
    p = parse(q, full)
    assert p.stops and p.stops[0].area.name == station
    assert p.landmark is None


@pytest.mark.parametrize("q", ["accessibilité fauteuil aéroport d'Orly", "prochain RER B à Roissy"])
def test_airport_words_alone_still_mean_the_airport(full: StopIndex, q: str) -> None:
    p = parse(q, full)
    assert p.stops and "roport" in p.stops[0].area.name


# ---------- after held-out set 6 (2026-11-23); wording differs from the eval ----------


@pytest.mark.parametrize(
    "q",
    [
        "is it allowed to vape on the platforms of the train stations",
        "est-ce qu'on peut fumer sur les quais des stations de RER",
    ],
)
def test_long_sentence_with_only_a_spelling_close_station_goes_to_the_ai(
    full: StopIndex, q: str
) -> None:
    assert parse(q, full).intent in ("unknown", "docs")


@pytest.mark.parametrize(
    ("q", "station"),
    [
        ("comment aller aux Catacombes depuis Nation", "Denfert-Rochereau"),
        ("next train to the Moulin Rouge", "Blanche"),
    ],
)
def test_new_landmarks_map_to_their_nearest_station(full: StopIndex, q: str, station: str) -> None:
    from app.agent.parser import _landmark
    from app.data.stops import normalize

    found = _landmark(normalize(q))
    assert found is not None and found[1] == station


def test_short_typo_departure_question_still_answered_by_rules(full: StopIndex) -> None:
    p = parse("prochain metro 4 garre du nord", full)
    assert p.intent == "next_departure" and p.stops[0].area.name == "Gare du Nord"
