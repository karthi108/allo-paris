"""Support check for document answers (RAG v2, after held-out set 5).

Before a document answer gets its citation, the chat model checks that every factual claim
in it is stated in the retrieved passages. An unsupported answer is replaced by "no
document": held-out set 5 showed a general-knowledge answer (resident parking) carrying a
Service Public citation because a related passage had been retrieved. Works across
languages (English answer, French passages), which word overlap did not.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.llm import LLMClient, LLMUnavailable

PASSAGE_CHARS = 1200
SYSTEM = (
    "You check an assistant's answer against official passages and tool data. Reply with "
    'JSON {"supported": true} if every factual claim in the answer is stated in, or '
    "directly follows from, the passages or tool data (the answer may be in another "
    "language and may rephrase). "
    'Reply {"supported": false} if any claim is missing from the passages, even if it is '
    "true in general. A citation in brackets at the end is not a claim."
)


class SupportChecker:
    def __init__(self, client: LLMClient) -> None:
        if client.provider != "openai":
            raise ValueError("support check is implemented for OpenAI only")
        self.client = client
        self.calls = 0

    def __call__(self, answer: str, passages: list[dict[str, Any]]) -> bool:
        """True when supported. Raises LLMUnavailable (the caller then keeps the answer:
        the guard and the retrieval floor still apply)."""
        if not passages:
            return False
        listing = "\n\n".join(
            f"[{n}] {p.get('title', '')}\n{str(p.get('passage', ''))[:PASSAGE_CHARS]}"
            for n, p in enumerate(passages[:8], 1)
        )
        body: dict[str, Any] = {
            "model": self.client.model,
            "max_tokens": 20,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Passages:\n{listing}\n\nAnswer: {answer}"},
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
        self.client.budget.record(
            int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        )
        self.calls += 1
        try:
            raw = json.loads(data["choices"][0]["message"]["content"] or "{}")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable("unexpected support-check response") from exc
        return raw.get("supported") is True
