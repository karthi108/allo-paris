"""Document corpus (data/docs.json, built by scripts/build_docs.py) and BM25 search.

In memory, no vector database, no extra dependency: the corpus is a few hundred passages.
Every passage carries its source, licence, URL and update date, so every answer built on
it can cite the document and the date (D-025).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.data.stops import normalize

# Words too common to help ranking (French and English), after normalize()
_STOP_WORDS = (
    "a au aux avec ce ces dans de des du elle en et est il je la le les leur lui ma mais "
    "me mon ne nous on ou par pas pour qu que qui sa se ses son sur ta te ton tu un une "
    "vous votre vos y d l j n s c m t comment quoi quel quelle quels quelles peut puis "
    "an and are as at be by can do does for from how i in is it my of or so that the to "
    "what when where which who why will with you your"
)
_STOP = frozenset(_STOP_WORDS.split())
K1, B = 1.5, 0.75
MIN_HITS = 2  # distinct query terms a passage must share to be returned


def terms(text: str) -> list[str]:
    """Normalised search terms: accents and case folded, stop words dropped, a plural 's'
    removed on long words so 'amendes' finds 'amende', feminine '-trice' read as '-teur'."""
    out = []
    for w in normalize(text).split():
        if w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        if len(w) > 6 and w.endswith("trice"):
            w = w[:-5] + "teur"  # médiatrice = médiateur (feminine form)
        out.append(w)
    return out


def citation_text(source: str, updated: str, lang: str) -> str:
    """Short citation, in brackets so it adds no sentence to a spoken answer."""
    y, m, d = (updated.split("-") + ["", "", ""])[:3]
    date = f"{d}/{m}/{y}" if y and m and d else updated
    if lang == "fr":
        return f"(Source : {source}, mise à jour le {date})"
    return f"(Source: {source}, updated {date})"


def cite_for(answer: str, outputs: list[dict[str, Any]], lang: str) -> str:
    """Citation of the retrieved passage the answer overlaps most with ("" if no passage).
    Added by code after the guard, so every answer built on a document cites it."""
    words = set(terms(answer))
    best: tuple[int, dict[str, Any]] | None = None
    for out in outputs:
        for p in out.get("passages") or []:
            overlap = len(
                words & set(terms(str(p.get("title", "")) + " " + str(p.get("passage", ""))))
            )
            if best is None or overlap > best[0]:
                best = (overlap, p)
    if best is None:
        return ""
    return citation_text(str(best[1].get("source", "")), str(best[1].get("updated", "")), lang)


def best_sentences(text: str, query: str, n: int = 2) -> str:
    """The n sentences of a passage sharing most terms with the query, in passage order,
    copied verbatim (rules-path excerpt: no rewording, so nothing can be invented)."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    q = set(terms(query))
    ranked = sorted(range(len(sentences)), key=lambda i: (-len(q & set(terms(sentences[i]))), i))
    keep = sorted(ranked[:n])
    return " ".join(sentences[i] for i in keep)


@dataclass(frozen=True)
class Doc:
    id: str
    kind: str  # accessibility | fiche
    title: str
    text: str
    source: str
    licence: str
    url: str
    updated: str  # YYYY-MM-DD
    station_zda: str = ""

    def citation(self, lang: str) -> str:
        return citation_text(self.source, self.updated, lang)

    def as_tool_output(self) -> dict[str, Any]:
        return {
            "doc_id": self.id,
            "title": self.title,
            "passage": self.text,
            "source": self.source,
            "updated": self.updated,
            "url": self.url,
        }


class Corpus:
    def __init__(self, docs: list[Doc]) -> None:
        self.docs = docs
        self.by_id = {d.id: d for d in docs}
        self.by_station: dict[str, Doc] = {
            d.station_zda: d for d in docs if d.kind == "accessibility" and d.station_zda
        }
        self._tf: list[Counter[str]] = []
        df: Counter[str] = Counter()
        for d in docs:
            tf = Counter(terms(d.title + " " + d.text))
            self._tf.append(tf)
            df.update(tf.keys())
        n = len(docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / n) if n else 0.0

    @classmethod
    def load(cls, path: Path) -> Corpus:
        rows = json.loads(path.read_text(encoding="utf-8"))["docs"]
        return cls(
            [
                Doc(
                    id=r["id"],
                    kind=r["kind"],
                    title=r["title"],
                    text=r["text"],
                    source=r["source"],
                    licence=r["licence"],
                    url=r["url"],
                    updated=r["updated"],
                    station_zda=str(r.get("station_zda") or ""),
                )
                for r in rows
            ]
        )

    def search(self, query: str, kind: str | None = None, limit: int = 3) -> list[Doc]:
        """BM25 ranking. Only passages sharing at least one term with the query are returned."""
        q = set(terms(query))
        if not q:
            return []
        scored: list[tuple[float, int]] = []
        for i, d in enumerate(self.docs):
            if kind and d.kind != kind:
                continue
            tf = self._tf[i]
            score = 0.0
            hits = 0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    hits += 1
                    norm = f + K1 * (1 - B + B * self._len[i] / self._avg)
                    score += self._idf[t] * f * (K1 + 1) / norm
            # Relevance floor: one shared word ("RATP") is not a match for "loi grève RATP"
            # (held-out set 4, 2026-11-23). A one-word query needs that word.
            if score > 0 and hits >= min(MIN_HITS, len(q)):
                scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self.docs[i] for _, i in scored[:limit]]
