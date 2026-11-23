"""RAG v2: vectors file, hybrid search floors, query embedder, LLM reranker (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.llm import Budget, LLMUnavailable, OpenAIClient
from app.rag.corpus import Corpus, Doc
from app.rag.embed import (
    QueryEmbedder,
    Vectors,
    corpus_hash,
    decode,
    encode,
    passage_text,
    unit,
)
from app.rag.rerank import LLMReranker
from app.rag.retriever import Retriever


def _doc(i: str, title: str, text: str) -> Doc:
    return Doc(i, "fiche", title, text, "Service Public / DILA", "LO 2.0", "u", "2026-11-16")


def _corpus() -> Corpus:
    return Corpus(
        [
            _doc("a", "Médiatrice SNCF", "Le recours à la médiatrice est gratuit."),
            _doc("b", "Carte mobilité inclusion", "La carte est demandée à la MDPH."),
            _doc("c", "Amende", "Contester un procès-verbal sous 3 mois."),
        ]
    )


def _vectors(c: Corpus, vecs: dict[str, list[float]]) -> Vectors:
    return Vectors({k: unit(v) for k, v in vecs.items()}, "m", 3)


def test_encode_decode_roundtrip() -> None:
    vecs = [unit([1.0, 2.0, 2.0]), unit([0.0, 1.0, 0.0])]
    back = decode(encode(vecs), 3)
    assert len(back) == 2
    assert all(
        abs(x - y) < 1e-6
        for a, b in zip(vecs, back, strict=True)
        for x, y in zip(a, b, strict=True)
    )


def test_vectors_refused_when_built_from_other_passages(tmp_path_factory: Any) -> None:
    c = _corpus()
    ids = [d.id for d in c.docs]
    texts = [passage_text(d.title, d.text) for d in c.docs]
    raw = {
        "model": "m",
        "dimensions": 3,
        "corpus_hash": corpus_hash(ids, texts),
        "ids": ids,
        "vectors": encode([unit([1, 0, 0]), unit([0, 1, 0]), unit([0, 0, 1])]),
    }
    path = Path("data") / "_test_vectors.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        assert Vectors.load(path, ids, texts) is not None
        changed = [*texts[:2], texts[2] + " (corrigé)"]
        assert Vectors.load(path, ids, changed) is None
    finally:
        path.unlink()


def test_hybrid_finds_passage_with_no_shared_word() -> None:
    c = _corpus()
    c.attach_vectors(_vectors(c, {"a": [1, 0, 0], "b": [0, 1, 0], "c": [0, 0, 1]}))
    q = "is mediation free of charge"  # no French word in common with passage a
    assert c.search(q, limit=3) == []  # BM25 alone finds nothing
    got = c.search(q, limit=3, qvec=unit([0.9, 0.1, 0.0]), floor=0.5)
    assert [d.id for d in got] == ["a"]


def test_hybrid_below_both_floors_returns_nothing() -> None:
    c = _corpus()
    c.attach_vectors(_vectors(c, {"a": [1, 0, 0], "b": [0, 1, 0], "c": [0, 0, 1]}))
    got = c.search("chien dans le metro", limit=3, qvec=unit([1, 1, 1]), floor=0.9)
    assert got == []


def test_without_vectors_search_is_bm25() -> None:
    c = _corpus()
    assert [d.id for d in c.search("médiatrice gratuit")] == ["a"]
    assert [d.id for d in c.search("médiatrice gratuit", qvec=[1.0, 0.0, 0.0])] == ["a"]


def test_query_embedder_caches_and_counts_budget() -> None:
    calls: list[dict[str, Any]] = []

    def post(url: str, h: dict[str, str], body: dict[str, Any], t: float) -> dict[str, Any]:
        calls.append(body)
        return {"data": [{"index": 0, "embedding": [3.0, 4.0]}], "usage": {"prompt_tokens": 5}}

    budget = Budget(1.0, 0.4, 1.6)
    emb = QueryEmbedder("k", budget, post=post, dimensions=2)
    v1 = emb("Médiation gratuite ?")
    v2 = emb("  médiation gratuite ?  ")
    assert v1 == v2 == pytest.approx([0.6, 0.8])
    assert len(calls) == 1 and calls[0]["dimensions"] == 2
    assert budget.spent_usd > 0


def test_query_embedder_without_key_is_unavailable() -> None:
    with pytest.raises(LLMUnavailable):
        QueryEmbedder("")("x")


def _client(content: str) -> OpenAIClient:
    def post(url: str, h: dict[str, str], body: dict[str, Any], t: float) -> dict[str, Any]:
        assert body["response_format"] == {"type": "json_object"}
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
        }

    return OpenAIClient("k", "gpt-test", Budget(1.0, 0.4, 1.6), post=post)


def test_reranker_orders_and_drops_bad_numbers() -> None:
    c = _corpus()
    rr = LLMReranker(_client('{"relevant": [3, 9, 1, 3]}'))
    got = rr.rerank("q", c.docs)
    assert [d.id for d in got] == ["c", "a"]
    assert rr.calls == 1 and rr.input_tokens == 100


def test_reranker_can_say_none() -> None:
    c = _corpus()
    assert LLMReranker(_client('{"relevant": []}')).rerank("chien", c.docs) == []


def test_reranker_bad_json_is_unavailable() -> None:
    c = _corpus()
    with pytest.raises(LLMUnavailable):
        LLMReranker(_client("not json")).rerank("q", c.docs)


# Retriever: hybrid + reranker with fallbacks, and "decline when docs don't cover it"


def _hybrid_corpus() -> Corpus:
    c = _corpus()
    c.attach_vectors(_vectors(c, {"a": [1, 0, 0], "b": [0, 1, 0], "c": [0, 0, 1]}))
    return c


def test_retriever_declines_when_reranker_finds_nothing() -> None:
    c = _hybrid_corpus()
    r = Retriever(c, lambda q: unit([1, 1, 1]), LLMReranker(_client('{"relevant": []}')))
    assert r.search("chien dans le métro", "peut-on prendre son chien ?") == []
    assert r.paths["reranked"] == 1


def test_retriever_keeps_reranker_order() -> None:
    c = _hybrid_corpus()
    r = Retriever(c, lambda q: unit([1, 1, 1]), LLMReranker(_client('{"relevant": [2]}')))
    got = r.search("médiatrice gratuit carte", "la médiation est gratuite ?")
    assert len(got) == 1


def test_retriever_falls_back_to_bm25_without_embeddings() -> None:
    def broken(q: str) -> list[float]:
        raise LLMUnavailable("budget")

    r = Retriever(_hybrid_corpus(), broken, LLMReranker(_client('{"relevant": []}')))
    assert [d.id for d in r.search("médiatrice gratuit")] == ["a"]
    assert r.paths["bm25"] == 1


def test_retriever_falls_back_to_hybrid_when_reranker_fails() -> None:
    r = Retriever(_hybrid_corpus(), lambda q: unit([1, 0, 0]), LLMReranker(_client("oops")))
    assert [d.id for d in r.search("médiatrice gratuit")][:1] == ["a"]
    assert r.paths["hybrid"] == 1


def test_search_docs_tool_says_no_document_when_declined() -> None:
    from app.agent.tools import Toolbox

    c = _hybrid_corpus()
    r = Retriever(c, lambda q: unit([1, 1, 1]), LLMReranker(_client('{"relevant": []}')))
    box = Toolbox(None, None, docs=c, retriever=r)  # type: ignore[arg-type]
    box.question = "can I take my dog on the metro?"
    out = json.loads(box.run("search_docs", {"query": "dog metro rules"}))
    assert out["passages"] == []
    assert "no document" in out["note"]


def test_support_checker_reads_the_verdict() -> None:
    from app.rag.verify import SupportChecker

    p = [{"title": "t", "passage": "Le recours est gratuit."}]
    assert SupportChecker(_client('{"supported": true}'))("It is free.", p) is True
    assert SupportChecker(_client('{"supported": false}'))("Ask your town hall.", p) is False
    assert SupportChecker(_client('{"supported": true}'))("x", []) is False
    with pytest.raises(LLMUnavailable):
        SupportChecker(_client("nope"))("x", p)


def test_reranker_sees_up_to_twenty_candidates() -> None:
    from app.rag.retriever import CANDIDATES

    docs = [_doc(str(i), "Carte mobilité inclusion", f"La carte section {i}.") for i in range(30)]
    c = Corpus(docs)
    c.attach_vectors(Vectors({d.id: unit([1.0, 0.0, 0.0]) for d in docs}, "m", 3))
    seen: list[int] = []

    class Spy(LLMReranker):
        def rerank(self, question: str, docs: Any) -> list[Doc]:  # type: ignore[override]
            seen.append(len(docs))
            return list(docs)[:1]

    r = Retriever(c, lambda q: unit([1.0, 0.0, 0.0]), Spy(_client('{"relevant": [1]}')))
    assert len(r.search("carte mobilité inclusion", "who can apply")) == 1
    assert seen == [CANDIDATES] and CANDIDATES == 20


def test_mistral_client_uses_its_url_and_names_tool_results() -> None:
    from app.agent.llm import MistralClient, ToolCall, make_client

    seen: list[str] = []

    def post(url: str, h: dict[str, str], body: dict[str, Any], t: float) -> dict[str, Any]:
        seen.append(url)
        msg = {
            "content": None,
            "tool_calls": [
                {
                    "id": "D681PevKs",
                    "function": {"name": "find_station", "arguments": '{"query": "Nation"}'},
                }
            ],
        }
        return {
            "choices": [{"message": msg}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

    client = make_client("mistral", "k", post=post)
    assert isinstance(client, MistralClient) and client.model == "mistral-small-latest"
    resp = client.chat("sys", [{"role": "user", "content": "hi"}], [])
    assert seen == ["https://api.mistral.ai/v1/chat/completions"]
    assert resp.tool_calls[0].name == "find_station" and resp.tool_calls[0].args == {
        "query": "Nation"
    }
    turn = client.tool_results_turn([(ToolCall("D681PevKs", "find_station", {}), "{}")])
    assert turn == [
        {"role": "tool", "tool_call_id": "D681PevKs", "name": "find_station", "content": "{}"}
    ]
