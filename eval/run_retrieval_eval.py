"""Retrieval eval for RAG v2: recall@k, MRR and "no passage" on covered / uncovered queries.

Measures search alone (no LLM answer). The query is the user's question as written.
Modes: bm25 (RAG v1), dense (embeddings only), hybrid (weighted RRF of both), and with
--rerank the hybrid top 10 reordered (or emptied) by the LLM reranker (app/rag/rerank.py).

    python eval/run_retrieval_eval.py --set dev [--sweep]
    python eval/run_retrieval_eval.py --set test     # frozen set: run once per version

Embeds the queries in one OpenAI call (ALLO_LLM_API_KEY, never printed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.llm import make_client  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.rag.corpus import COS_FLOOR, Corpus  # noqa: E402
from app.rag.embed import PRICE_PER_M, Vectors, embed_batch, passage_text  # noqa: E402
from app.rag.rerank import LLMReranker  # noqa: E402
from app.rag.retriever import CANDIDATES  # noqa: E402

KS = (1, 3, 5)
RERANK_CANDIDATES = CANDIDATES  # same as the app
SETS = {"dev": "retrieval_dev.jsonl", "test": "retrieval_test.jsonl"}


def load_corpus() -> Corpus:
    corpus = Corpus.load(ROOT / "data" / "docs.json")
    vecs = Vectors.load(
        ROOT / "data" / "doc_vectors.json",
        [d.id for d in corpus.docs],
        [passage_text(d.title, d.text) for d in corpus.docs],
    )
    if vecs is None:
        raise SystemExit("data/doc_vectors.json missing or stale: run scripts/build_vectors.py")
    corpus.attach_vectors(vecs)
    return corpus


def ranked_ids(
    corpus: Corpus, mode: str, q: str, qvec: list[float], floor: float, limit: int
) -> list[str]:
    if mode == "bm25":
        return [d.id for d in corpus.search(q, limit=limit)]
    if mode == "dense":
        return [corpus.docs[i].id for _, i in corpus.dense(qvec, floor=floor)[:limit]]
    return [d.id for d in corpus.search(q, limit=limit, qvec=qvec, floor=floor)]


def score(rows: list[dict[str, Any]], results: list[list[str]]) -> dict[str, Any]:
    covered = [(r, ids) for r, ids in zip(rows, results, strict=True) if r["relevant"]]
    none = [(r, ids) for r, ids in zip(rows, results, strict=True) if not r["relevant"]]
    out: dict[str, Any] = {"covered": len(covered), "uncovered": len(none)}
    for k in KS:
        hit = sum(1 for r, ids in covered if set(ids[:k]) & set(r["relevant"]))
        out[f"recall@{k}"] = round(hit / len(covered), 3) if covered else None
    rr = 0.0
    for r, ids in covered:
        for pos, i in enumerate(ids[:5]):
            if i in r["relevant"]:
                rr += 1 / (pos + 1)
                break
    out["mrr@5"] = round(rr / len(covered), 3) if covered else None
    out["covered_empty"] = sum(1 for _, ids in covered if not ids)
    out["uncovered_declined"] = sum(1 for _, ids in none if not ids)
    by_kind: dict[str, list[int]] = {}
    for r, ids in covered:
        by_kind.setdefault(r["kind"], [0, 0])
        by_kind[r["kind"]][1] += 1
        if set(ids[:5]) & set(r["relevant"]):
            by_kind[r["kind"]][0] += 1
    out["recall@5_by_kind"] = {k: f"{a}/{b}" for k, (a, b) in by_kind.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="dev")
    ap.add_argument("--floor", type=float, default=COS_FLOOR)
    ap.add_argument("--sweep", action="store_true", help="dev only: try several cosine floors")
    ap.add_argument("--rerank", action="store_true", help="also score with the reranker")
    ap.add_argument("--save", action="store_true", help="write eval/results/retrieval_*.json")
    args = ap.parse_args()
    if args.sweep and args.set != "dev":
        raise SystemExit("--sweep is for the dev set only (the test set is never tuned against)")

    rows = [
        json.loads(line)
        for line in (ROOT / "eval" / SETS[args.set]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = load_corpus()
    s = get_settings()
    t0 = time.perf_counter()
    qvecs, tokens = embed_batch([r["q"] for r in rows], s.llm_api_key)
    embed_ms = (time.perf_counter() - t0) * 1000

    floors = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50] if args.sweep else [args.floor]
    report: dict[str, Any] = {
        "set": args.set,
        "queries": len(rows),
        "embedding_tokens": tokens,
        "embedding_cost_usd": round(tokens * PRICE_PER_M / 1_000_000, 6),
        "embed_call_ms_all_queries": round(embed_ms),
        "runs": [],
    }
    reranker = None
    if args.rerank:
        client = make_client("openai", s.llm_api_key, s.llm_model, daily_usd=5.0)
        if client is None:
            raise SystemExit("--rerank needs ALLO_LLM_API_KEY")
        reranker = LLMReranker(client)
    for floor in floors:
        for mode in ("bm25", "dense", "hybrid"):
            if mode == "bm25" and floor != floors[0]:
                continue
            t1 = time.perf_counter()
            results = [
                ranked_ids(corpus, mode, r["q"], v, floor, 5)
                for r, v in zip(rows, qvecs, strict=True)
            ]
            ms = (time.perf_counter() - t1) * 1000 / len(rows)
            run = {"mode": mode, "floor": None if mode == "bm25" else floor}
            run.update(score(rows, results))
            run["search_ms_per_query"] = round(ms, 2)
            report["runs"].append(run)
            print(json.dumps(run, ensure_ascii=False))
            if reranker is not None and mode == "hybrid":
                wide = [
                    ranked_ids(corpus, mode, r["q"], v, floor, RERANK_CANDIDATES)
                    for r, v in zip(rows, qvecs, strict=True)
                ]
                t2 = time.perf_counter()
                reranked = [
                    reranker.rank(r["q"], ids, corpus)[:5]
                    for r, ids in zip(rows, wide, strict=True)
                ]
                rms = (time.perf_counter() - t2) * 1000 / len(rows)
                rrun = {"mode": f"{mode}+rerank", "floor": floor, "reranker": reranker.name}
                rrun.update(score(rows, reranked))
                rrun["rerank_ms_per_query"] = round(rms)
                rrun["rerank_tokens_in_out"] = [reranker.input_tokens, reranker.output_tokens]
                rrun["rerank_cost_usd"] = round(client.budget.spent_usd, 5)
                report["runs"].append(rrun)
                print(json.dumps(rrun, ensure_ascii=False))
            if mode == "hybrid":
                report.setdefault("detail", {})[str(floor)] = [
                    {"q": r["q"], "relevant": r["relevant"], "got": ids}
                    for r, ids in zip(rows, results, strict=True)
                ]
    print(
        f"embedding: {tokens} tokens, ${report['embedding_cost_usd']}, "
        f"{report['embed_call_ms_all_queries']} ms for all queries in one call"
    )
    if args.save:
        git = ["git", "rev-parse", "--short", "HEAD"]
        done = subprocess.run(git, capture_output=True, text=True, cwd=ROOT)  # noqa: S603, S607
        commit = done.stdout.strip()
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M")
        out = ROOT / "eval" / "results" / f"retrieval_{args.set}_{stamp}_{commit}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
