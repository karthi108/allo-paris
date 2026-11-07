"""In-memory service metrics for the public /metrics page. No question text is kept."""

from __future__ import annotations

import threading
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any


def _pct(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


class Metrics:
    def __init__(self, window: int = 500) -> None:
        self._lock = threading.Lock()
        self.started_at = datetime.now(UTC)
        self.paths: Counter[str] = Counter()
        self.intents: Counter[str] = Counter()
        self.latency: dict[str, deque[int]] = {}
        self.window = window
        self.guard_retries = 0
        self.guard_fallbacks = 0
        self.ai_unavailable = 0

    def record(
        self,
        path: str,
        intent: str,
        latency_ms: int,
        retried: bool = False,
        fallback: bool = False,
    ) -> None:
        with self._lock:
            self.paths[path] += 1
            self.intents[intent] += 1
            self.latency.setdefault(path, deque(maxlen=self.window)).append(latency_ms)
            self.guard_retries += int(retried)
            self.guard_fallbacks += int(fallback)
            self.ai_unavailable += int(path == "rules_fallback")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self.paths.values())
            return {
                "since": self.started_at.isoformat(timespec="seconds"),
                "questions": total,
                "by_path": dict(self.paths),
                "ai_share": round((self.paths["ai"] + self.paths["ai_fallback"]) / total, 3)
                if total
                else 0.0,
                "latency_ms": {
                    p: {"p50": _pct(list(v), 0.5), "p95": _pct(list(v), 0.95), "n": len(v)}
                    for p, v in self.latency.items()
                },
                "grounding": {
                    "retries": self.guard_retries,
                    "blocked_to_fallback": self.guard_fallbacks,
                },
                "ai_unavailable_fell_back_to_rules": self.ai_unavailable,
                "top_intents": dict(self.intents.most_common(8)),
            }
