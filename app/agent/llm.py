"""Provider-agnostic LLM client with tool calling (OpenAI or Anthropic), plain HTTP.

Both adapters return the same LLMResponse, so the agent loop does not care which
provider is configured. A daily spending cap is enforced before every call.
Prices are configurable (ALLO_LLM_PRICE_IN / _OUT, per million tokens) because they
change; the defaults are rough and should be checked on the provider's pricing page.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PostJson = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class LLMUnavailable(Exception):
    """No key, budget reached, or provider error: the caller falls back to rules."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


def http_post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(  # noqa: S310 (fixed provider https URLs)
        url, data=data, headers={**headers, "content-type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            result: dict[str, Any] = json.load(resp)
            return result
    except urllib.error.HTTPError as exc:
        raise LLMUnavailable(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise LLMUnavailable(type(exc).__name__) from exc


class Budget:
    """Daily spending cap in USD (approximate, from token usage)."""

    def __init__(self, daily_usd: float, price_in: float, price_out: float) -> None:
        self.daily_usd = daily_usd
        self.price_in = price_in  # USD per million input tokens
        self.price_out = price_out
        self._lock = threading.Lock()
        self._day = datetime.now(UTC).date()
        self.spent_usd = 0.0
        self.calls_today = 0

    def _roll(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self.spent_usd, self.calls_today = today, 0.0, 0

    def check(self) -> None:
        with self._lock:
            self._roll()
            if self.spent_usd >= self.daily_usd:
                raise LLMUnavailable("daily LLM budget reached")

    def record(self, input_tokens: int, output_tokens: int) -> float:
        cost = (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000
        with self._lock:
            self._roll()
            self.spent_usd += cost
            self.calls_today += 1
        return cost


class LLMClient:
    provider = "none"

    def __init__(
        self,
        api_key: str,
        model: str,
        budget: Budget,
        timeout: float = 15.0,
        post: PostJson = http_post_json,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.budget = budget
        self.timeout = timeout
        self.post = post

    def chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMUnavailable("no LLM key configured")
        self.budget.check()
        resp = self._chat(system, messages, tools)
        self.budget.record(resp.input_tokens, resp.output_tokens)
        return resp

    def _chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> LLMResponse:
        raise NotImplementedError

    # Conversation helpers: each provider stores tool turns differently
    def assistant_turn(self, resp: LLMResponse) -> dict[str, Any]:
        raise NotImplementedError

    def tool_results_turn(self, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    provider = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def _chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": 500,
            "system": system,
            "messages": messages,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = self.post(self.URL, headers, body, self.timeout)
        text, calls = "", []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        usage = data.get("usage") or {}
        return LLMResponse(
            text.strip(),
            calls,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )

    def assistant_turn(self, resp: LLMResponse) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if resp.text:
            content.append({"type": "text", "text": resp.text})
        for c in resp.tool_calls:
            content.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
        return {"role": "assistant", "content": content}

    def tool_results_turn(self, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": c.id, "content": out}
                    for c, out in results
                ],
            }
        ]


class OpenAIClient(LLMClient):
    provider = "openai"
    URL = "https://api.openai.com/v1/chat/completions"

    def _chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": 500,
            "messages": [{"role": "system", "content": system}, *messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
        }
        headers = {"authorization": f"Bearer {self.api_key}"}
        data = self.post(self.URL, headers, body, self.timeout)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("unexpected OpenAI response") from exc
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.get("id", ""), fn.get("name", ""), args))
        usage = data.get("usage") or {}
        return LLMResponse(
            (msg.get("content") or "").strip(),
            calls,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    def assistant_turn(self, resp: LLMResponse) -> dict[str, Any]:
        turn: dict[str, Any] = {"role": "assistant", "content": resp.text or None}
        if resp.tool_calls:
            turn["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.args)},
                }
                for c in resp.tool_calls
            ]
        return turn

    def tool_results_turn(self, results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [{"role": "tool", "tool_call_id": c.id, "content": out} for c, out in results]


DEFAULT_MODELS = {"anthropic": "claude-haiku-4-5", "openai": "gpt-4.1-mini"}
# Rough USD per million tokens (input, output). Check the provider's pricing page.
DEFAULT_PRICES = {"anthropic": (1.0, 5.0), "openai": (0.4, 1.6)}


def make_client(
    provider: str,
    api_key: str,
    model: str = "",
    daily_usd: float = 1.0,
    price_in: float | None = None,
    price_out: float | None = None,
    post: PostJson = http_post_json,
) -> LLMClient | None:
    provider = provider.lower().strip()
    if provider not in DEFAULT_MODELS or not api_key:
        return None
    p_in, p_out = DEFAULT_PRICES[provider]
    budget = Budget(
        daily_usd, p_in if price_in is None else price_in, p_out if price_out is None else price_out
    )
    cls: type[LLMClient] = AnthropicClient if provider == "anthropic" else OpenAIClient
    return cls(api_key, model or DEFAULT_MODELS[provider], budget, post=post)
