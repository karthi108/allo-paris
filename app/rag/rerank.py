"""LLM reranker for RAG v2 (D-026): the chat model reads the candidate passages and returns
the ones that answer the question, best first, or none.

Chosen over a local cross-encoder because the Render free plan (512 MB RAM, 0.1 CPU) cannot
run one next to the app. "None" is the point: it lets search say "no document" when the
words or the vectors are close but no passage answers (cosine alone could not, dev set).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.agent.llm import LLMClient, LLMUnavailable
from app.rag.corpus import Corpus, Doc

PASSAGE_CHARS = 700
SYSTEM = (
    "You rank passages for a search engine. Given a question and numbered passages, "
    'return JSON {"relevant": [numbers]} listing only the passages that contain '
    "information answering the question, most useful first. A passage about a related "
    "topic that does not answer the question is not relevant. If none answers it, return "
    '{"relevant": []}. Do not answer the question.'
)


class LLMReranker:
    name = "llm"

    def __init__(self, client: LLMClient) -> None:
        if client.provider != "openai":
            raise ValueError("LLM reranker is implemented for OpenAI only")
        self.client = client
        self.name = f"llm:{client.model}"
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def rerank(self, question: str, docs: Sequence[Doc]) -> list[Doc]:
        """The docs that answer the question, best first ([] if none). Raises LLMUnavailable."""
        if not docs:
            return []
        listing = "\n\n".join(
            f"[{n}] {d.title}\n{d.text[:PASSAGE_CHARS]}" for n, d in enumerate(docs, 1)
        )
        body: dict[str, Any] = {
            "model": self.client.model,
            "max_tokens": 60,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Question: {question}\n\nPassages:\n{listing}"},
            ],
        }
        self.client.budget.check()
        data = self.client.post(
            "https://api.openai.com/v1/chat/completions",
            {"authorization": f"Bearer {self.client.api_key}"},
            body,
            self.client.timeout,
        )
        usage = data.get("usage") or {}
        tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        self.client.budget.record(tin, tout)
        self.input_tokens += tin
        self.output_tokens += tout
        self.calls += 1
        try:
            raw = json.loads(data["choices"][0]["message"]["content"] or "{}")
            picks = [int(n) for n in raw.get("relevant", [])]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable("unexpected reranker response") from exc
        out: list[Doc] = []
        for n in picks:
            if 1 <= n <= len(docs) and docs[n - 1] not in out:
                out.append(docs[n - 1])
        return out

    def rank(self, question: str, ids: Sequence[str], corpus: Corpus) -> list[str]:
        """Eval helper: ids in, reranked ids out."""
        return [d.id for d in self.rerank(question, [corpus.by_id[i] for i in ids])]
