"""Embed every passage of data/docs.json once and save data/doc_vectors.json (RAG v2, D-026).

Uses ALLO_LLM_API_KEY (OpenAI) from the environment or .env; the key is never printed.
Run again after scripts/build_docs.py: the app refuses vectors built from other passages.
Cost: the whole corpus is roughly 20k tokens, a fraction of a US cent.

    python scripts/build_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.rag.corpus import Corpus  # noqa: E402
from app.rag.embed import (  # noqa: E402
    BATCH,
    DIMENSIONS,
    MODEL,
    PRICE_PER_M,
    corpus_hash,
    embed_batch,
    encode,
    passage_text,
)


def main() -> int:
    s = get_settings()
    if not s.llm_api_key or s.llm_provider != "openai":
        print("Needs ALLO_LLM_PROVIDER=openai and ALLO_LLM_API_KEY (in .env or the environment).")
        return 1
    corpus = Corpus.load(s.docs_path)
    ids = [d.id for d in corpus.docs]
    texts = [passage_text(d.title, d.text) for d in corpus.docs]
    vecs: list[list[float]] = []
    tokens = 0
    for i in range(0, len(texts), BATCH):
        batch, t = embed_batch(texts[i : i + BATCH], s.llm_api_key)
        vecs.extend(batch)
        tokens += t
        print(f"embedded {len(vecs)}/{len(texts)}")
    out = {
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "corpus_hash": corpus_hash(ids, texts),
        "ids": ids,
        "vectors": encode(vecs),
    }
    path = ROOT / "data" / "doc_vectors.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    cost = tokens * PRICE_PER_M / 1_000_000
    print(f"saved {path.name}: {len(ids)} passages, {tokens} tokens, ~${cost:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
