"""Dense retrieval for RAG v2 (D-026): OpenAI embeddings, plain HTTP, no extra dependency.

Passage vectors are computed once by scripts/build_vectors.py and committed as
data/doc_vectors.json (base64 float32, unit length). At question time one embedding call
turns the query into a vector; cosine similarity is a dot product in pure Python
(522 passages x 512 dimensions, fast enough without numpy). No vector database.
"""

from __future__ import annotations

import array
import base64
import hashlib
import json
import math
import threading
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.agent.llm import Budget, LLMUnavailable, PostJson, http_post_json

URL = "https://api.openai.com/v1/embeddings"
MODEL = "text-embedding-3-small"
DIMENSIONS = 512
# USD per million input tokens for text-embedding-3-small (OpenAI pricing page, read
# 2026-11-23). Check it again if the model changes.
PRICE_PER_M = 0.02
BATCH = 100


def unit(vec: Sequence[float]) -> list[float]:
    """Scale to length 1 (the API says its vectors are normalised; shortened ones are
    normalised again here so a dot product is always the cosine)."""
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else list(vec)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def corpus_hash(ids: Sequence[str], texts: Sequence[str]) -> str:
    """Fingerprint of the passages the vectors were built from: a stale vector file
    (corpus rebuilt, vectors not) is refused instead of silently mismatching."""
    h = hashlib.sha256()
    for i, t in zip(ids, texts, strict=True):
        h.update(i.encode())
        h.update(b"\0")
        h.update(t.encode())
        h.update(b"\0")
    return h.hexdigest()


def passage_text(title: str, text: str) -> str:
    return f"{title}\n{text}"


def embed_batch(
    texts: list[str],
    api_key: str,
    post: PostJson = http_post_json,
    timeout: float = 30.0,
    dimensions: int = DIMENSIONS,
) -> tuple[list[list[float]], int]:
    """Unit vectors for texts (same order) and the input tokens billed."""
    body: dict[str, Any] = {"model": MODEL, "input": texts, "dimensions": dimensions}
    data = post(URL, {"authorization": f"Bearer {api_key}"}, body, timeout)
    try:
        rows = sorted(data["data"], key=lambda r: int(r["index"]))
        vecs = [unit([float(x) for x in r["embedding"]]) for r in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMUnavailable("unexpected embeddings response") from exc
    if len(vecs) != len(texts):
        raise LLMUnavailable("embeddings count mismatch")
    tokens = int((data.get("usage") or {}).get("prompt_tokens", 0))
    return vecs, tokens


def encode(vecs: list[list[float]]) -> str:
    return base64.b64encode(array.array("f", [x for v in vecs for x in v]).tobytes()).decode()


def decode(b64: str, dimensions: int) -> list[list[float]]:
    flat = array.array("f")
    flat.frombytes(base64.b64decode(b64))
    return [list(flat[i : i + dimensions]) for i in range(0, len(flat), dimensions)]


class Vectors:
    """Passage vectors loaded from data/doc_vectors.json, by passage id."""

    def __init__(self, by_id: dict[str, list[float]], model: str, dimensions: int) -> None:
        self.by_id = by_id
        self.model = model
        self.dimensions = dimensions

    @classmethod
    def load(cls, path: Path, ids: Sequence[str], texts: Sequence[str]) -> Vectors | None:
        """None when the file is missing or was built from other passages."""
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("corpus_hash") != corpus_hash(ids, texts):
            return None
        dims = int(raw["dimensions"])
        vecs = decode(raw["vectors"], dims)
        return cls(dict(zip(raw["ids"], vecs, strict=True)), str(raw["model"]), dims)


class QueryEmbedder:
    """One embedding call per new query, with a small cache and the daily LLM budget."""

    def __init__(
        self,
        api_key: str,
        budget: Budget | None = None,
        post: PostJson = http_post_json,
        timeout: float = 5.0,
        dimensions: int = DIMENSIONS,
        cache_size: int = 256,
    ) -> None:
        self.api_key = api_key
        self.budget = budget
        self.post = post
        self.timeout = timeout
        self.dimensions = dimensions
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()
        self.calls = 0
        self.tokens = 0

    def __call__(self, query: str) -> list[float]:
        key = query.strip().lower()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        if not self.api_key:
            raise LLMUnavailable("no key for embeddings")
        if self.budget is not None:
            self.budget.check()
        vecs, tokens = embed_batch(
            [query], self.api_key, self.post, self.timeout, dimensions=self.dimensions
        )
        if self.budget is not None:
            self.budget.record_usd(tokens * PRICE_PER_M / 1_000_000)
        with self._lock:
            self.calls += 1
            self.tokens += tokens
            self._cache[key] = vecs[0]
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)
        return vecs[0]
