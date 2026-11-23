"""RAG v2 search used by the search_docs tool: hybrid BM25 + embeddings, then the LLM
reranker, each step falling back to the previous one when the API is unavailable
(no key, budget reached, timeout). Without embeddings and reranker it is RAG v1 (BM25).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from app.agent.llm import LLMClient, LLMUnavailable
from app.rag.corpus import Corpus, Doc
from app.rag.embed import DIMENSIONS, QueryEmbedder, Vectors, passage_text
from app.rag.rerank import LLMReranker

log = logging.getLogger(__name__)

# Hybrid passages shown to the reranker. 10 → 20 on 2026-11-23: the CMI fiche repeats near-
# identical sections per card type, so "who can apply for the CMI priority card" had its answer
# ranked 7th by the embeddings but outside the fused top 10 (live check). Dev retrieval set:
# unchanged at 1.0; reranker cost per document question ≈ $0.00044 → $0.00078.
CANDIDATES = 20
# With the reranker deciding relevance, the cosine floor only trims obvious noise: at 0.46
# (no reranker) an English question with no French word in common got no candidate at all
# (retrieval test set, 2026-11-23). Checked on the dev set: the reranker still declines.
RERANK_COS_FLOOR = 0.30


class Retriever:
    def __init__(
        self,
        corpus: Corpus,
        embed: Callable[[str], list[float]] | None = None,
        reranker: LLMReranker | None = None,
    ) -> None:
        self.corpus = corpus
        self.embed = embed if corpus.vectors is not None else None
        self.reranker = reranker
        self.paths: Counter[str] = Counter()  # which path answered, for /metrics and tests

    def search(self, query: str, question: str = "", limit: int = 5) -> list[Doc]:
        """query: the model's keywords plus the user's words (BM25); question: the user's
        own question (embedding and reranker). Returns at most limit passages, maybe none."""
        question = question or query
        qvec = None
        if self.embed is not None:
            try:
                qvec = self.embed(question)
            except LLMUnavailable as exc:
                log.info("embedding unavailable (%s): BM25 only", exc)
        if qvec is None:
            self.paths["bm25"] += 1
            return self.corpus.search(query, limit=limit)
        if self.reranker is None:
            self.paths["hybrid"] += 1
            return self.corpus.search(query, limit=limit, qvec=qvec)
        cands = self.corpus.search(query, limit=CANDIDATES, qvec=qvec, floor=RERANK_COS_FLOOR)
        if not cands:
            self.paths["hybrid_none"] += 1
            return []
        try:
            picked = self.reranker.rerank(question, cands)
        except LLMUnavailable as exc:
            log.info("reranker unavailable (%s): hybrid order", exc)
            self.paths["hybrid"] += 1
            return self.corpus.search(query, limit=limit, qvec=qvec)
        self.paths["reranked"] += 1
        return picked[:limit]


def make_retriever(corpus: Corpus, docs_path: Path, llm: LLMClient | None) -> Retriever:
    """Hybrid + reranker when the LLM provider is OpenAI and data/doc_vectors.json matches
    the corpus; otherwise BM25 only (Anthropic has no embeddings endpoint used here)."""
    vectors = Vectors.load(
        docs_path.with_name("doc_vectors.json"),
        [d.id for d in corpus.docs],
        [passage_text(d.title, d.text) for d in corpus.docs],
    )
    if vectors is None:
        log.warning("doc_vectors.json missing or stale: document search is BM25 only")
    corpus.attach_vectors(vectors)
    if llm is None or llm.provider != "openai":
        return Retriever(corpus)
    embed = QueryEmbedder(llm.api_key, llm.budget, post=llm.post, dimensions=DIMENSIONS)
    return Retriever(corpus, embed, LLMReranker(llm))
