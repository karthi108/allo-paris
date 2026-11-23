"""Lightweight ML intent classifier (D-026): multinomial logistic regression over word and
character n-grams, trained offline (scripts/train_intent.py), pure Python, no dependency.

It sits between the rules and the LLM: when the rules cannot classify a question, a
confident prediction of out_of_scope answers with the refusal template without an LLM call
(app/agent/dialog.py). Other labels still go to the LLM, which needs to extract places,
lines and times. Measured against rules and LLM on eval/intents_test.jsonl.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Iterable
from pathlib import Path

from app.data.stops import normalize

LABELS = ("departures", "status", "route", "velib", "ev", "access", "docs", "out_of_scope")


def features(text: str) -> list[str]:
    """Word unigrams and bigrams, and character 3- to 5-grams inside words (typos, 'vlib')."""
    words = normalize(text).split()
    out = [f"w:{w}" for w in words]
    out += [f"b:{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
    for w in words:
        padded = f"<{w}>"
        for n in (3, 4, 5):
            out += [f"c:{padded[i : i + n]}" for i in range(len(padded) - n + 1)]
    return out


def _softmax(z: list[float]) -> list[float]:
    m = max(z)
    e = [math.exp(x - m) for x in z]
    s = sum(e)
    return [x / s for x in e]


class IntentModel:
    def __init__(self, weights: dict[str, list[float]], bias: list[float]) -> None:
        self.weights = weights
        self.bias = bias

    def proba(self, text: str) -> list[float]:
        z = list(self.bias)
        for f in features(text):
            w = self.weights.get(f)
            if w is not None:
                for k in range(len(LABELS)):
                    z[k] += w[k]
        return _softmax(z)

    def predict(self, text: str) -> tuple[str, float]:
        p = self.proba(text)
        k = max(range(len(LABELS)), key=lambda i: p[i])
        return LABELS[k], p[k]

    @classmethod
    def train(
        cls,
        rows: Iterable[tuple[str, str]],
        epochs: int = 40,
        lr: float = 0.3,
        l2: float = 1e-4,
        seed: int = 7,
    ) -> IntentModel:
        data = [(features(q), LABELS.index(y)) for q, y in rows]
        rng = random.Random(seed)  # noqa: S311 (shuffling, not security)
        weights: dict[str, list[float]] = {}
        bias = [0.0] * len(LABELS)
        for epoch in range(epochs):
            rng.shuffle(data)
            step = lr / (1 + epoch * 0.1)
            for feats, y in data:
                z = list(bias)
                for f in feats:
                    w = weights.get(f)
                    if w is not None:
                        for k in range(len(LABELS)):
                            z[k] += w[k]
                p = _softmax(z)
                grad = [p[k] - (1.0 if k == y else 0.0) for k in range(len(LABELS))]
                for k in range(len(LABELS)):
                    bias[k] -= step * grad[k]
                for f in feats:
                    w = weights.setdefault(f, [0.0] * len(LABELS))
                    for k in range(len(LABELS)):
                        w[k] -= step * (grad[k] + l2 * w[k])
        return cls(weights, bias)

    def save(self, path: Path, meta: dict[str, object]) -> None:
        kept = {
            f: [round(x, 4) for x in w] for f, w in self.weights.items() if max(map(abs, w)) > 1e-3
        }
        path.write_text(
            json.dumps({"labels": LABELS, "bias": self.bias, "weights": kept, "meta": meta}),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> IntentModel | None:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if tuple(raw["labels"]) != LABELS:
            return None
        return cls(raw["weights"], raw["bias"])
