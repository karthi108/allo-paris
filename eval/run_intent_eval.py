"""Intent comparison on eval/intents_test.jsonl: rules / ML classifier / LLM / hybrid.

- rules: app.agent.parser.parse, its intent mapped to the 8 labels; "unknown" and the
  intents the dialog hands to the AI (unsupported_time, clarify_airport) are abstentions.
- ml: data/intent_model.json (scripts/train_intent.py), argmax over 8 labels.
- llm: gpt-4.1-mini zero-shot, JSON {"label": ...}, one call per question.
- hybrid: rules when they classify; else ML when its probability >= ML_THRESHOLD (fixed
  before the run, not tuned on this set); else the LLM.
An abstention counts as wrong. Cost: tokens x the configured default prices.

    python eval/run_intent_eval.py [--save]
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

from app.agent.intent_ml import LABELS, IntentModel  # noqa: E402
from app.agent.llm import LLMClient, make_client  # noqa: E402
from app.agent.parser import parse  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.stops import StopIndex  # noqa: E402

ML_THRESHOLD = 0.6
RULES_MAP = {
    "next_departure": "departures",
    "line_status": "status",
    "velib": "velib",
    "ev": "ev",
    "accessibility": "access",
    "docs": "docs",
    "unsupported_route": "route",
    "unsupported_price": "out_of_scope",
    "unsupported_bus": "out_of_scope",
    "refused": "out_of_scope",
}
LLM_SYSTEM = (
    "Classify a user question to a Paris transport assistant into exactly one label: "
    "departures (next departures of a line at a station), status (disruptions or whether a "
    "line runs), route (how to go from one place to another), velib (bike share), ev (electric "
    "car chargers), access (wheelchair or step-free access at a station), docs (rules, fines, "
    "SNCF mediator, disability card CMI, what is allowed on board), out_of_scope (prices, "
    'buses, weather, jokes, instructions to the assistant, anything else). Reply JSON {"label": '
    '"..."}.'
)


def llm_label(client: LLMClient, q: str) -> tuple[str | None, int, int]:
    body: dict[str, Any] = {
        "model": client.model,
        "max_tokens": 12,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": LLM_SYSTEM}, {"role": "user", "content": q}],
    }
    data = client.post(
        "https://api.openai.com/v1/chat/completions",
        {"authorization": f"Bearer {client.api_key}"},
        body,
        client.timeout,
    )
    usage = data.get("usage") or {}
    tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    client.budget.record(tin, tout)
    try:
        label = json.loads(data["choices"][0]["message"]["content"]).get("label")
    except (KeyError, IndexError, TypeError, ValueError):
        label = None
    return (label if label in LABELS else None), tin, tout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    rows = [
        json.loads(x)
        for x in (ROOT / "eval" / "intents_test.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    index = StopIndex.load(ROOT / "data" / "stops.json")
    model = IntentModel.load(ROOT / "data" / "intent_model.json")
    if model is None:
        raise SystemExit("data/intent_model.json missing: run scripts/train_intent.py")
    s = get_settings()
    client = make_client("openai", s.llm_api_key, s.llm_model, daily_usd=2.0)
    if client is None:
        raise SystemExit("needs ALLO_LLM_API_KEY (OpenAI)")

    out: list[dict[str, Any]] = []
    for r in rows:
        q = r["q"]
        t = time.perf_counter()
        rule = RULES_MAP.get(parse(q, index).intent)
        rule_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        ml, p = model.predict(q)
        ml_ms = (time.perf_counter() - t) * 1000
        spent0 = client.budget.spent_usd
        t = time.perf_counter()
        llm, tin, tout = llm_label(client, q)
        llm_ms = (time.perf_counter() - t) * 1000
        llm_usd = client.budget.spent_usd - spent0
        if rule is not None:
            hyb, src, hyb_ms, hyb_usd = rule, "rules", rule_ms, 0.0
        elif p >= ML_THRESHOLD:
            hyb, src, hyb_ms, hyb_usd = ml, "ml", rule_ms + ml_ms, 0.0
        else:
            hyb, src = llm, "llm"
            hyb_ms, hyb_usd = rule_ms + ml_ms + llm_ms, llm_usd
        out.append(
            {
                "q": q,
                "label": r["label"],
                "rules": rule,
                "ml": ml,
                "ml_p": round(p, 3),
                "llm": llm,
                "hybrid": hyb,
                "hybrid_src": src,
                "ms": {"rules": rule_ms, "ml": ml_ms, "llm": llm_ms, "hybrid": hyb_ms},
                "usd": {"llm": llm_usd, "hybrid": hyb_usd},
            }
        )

    def pct(xs: list[float], q: float) -> float:
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(q * len(xs)))]

    report: dict[str, Any] = {"questions": len(out), "ml_threshold": ML_THRESHOLD, "systems": {}}
    for sysname in ("rules", "ml", "llm", "hybrid"):
        ok = sum(1 for x in out if x[sysname] == x["label"])
        abstain = sum(1 for x in out if x[sysname] is None)
        ms = [x["ms"][sysname] for x in out]
        usd = sum(x["usd"].get(sysname, 0.0) for x in out)
        by = {
            lb: f"{sum(1 for x in out if x['label'] == lb and x[sysname] == lb)}/"
            f"{sum(1 for x in out if x['label'] == lb)}"
            for lb in LABELS
        }
        report["systems"][sysname] = {
            "accuracy": round(ok / len(out), 3),
            "correct": ok,
            "abstained": abstain,
            "cost_usd_per_question": round(usd / len(out), 6),
            "latency_p50_ms": round(pct(ms, 0.5), 2),
            "latency_p95_ms": round(pct(ms, 0.95), 2),
            "by_label": by,
        }
        print(sysname, json.dumps(report["systems"][sysname], ensure_ascii=False))
    src = {k: sum(1 for x in out if x["hybrid_src"] == k) for k in ("rules", "ml", "llm")}
    report["hybrid_sources"] = src
    print("hybrid sources:", src)
    for x in out:
        if x["hybrid"] != x["label"]:
            src, got, want = x["hybrid_src"], x["hybrid"], x["label"]
            print(f"  hybrid wrong ({src}): {x['q']!r} -> {got} (want {want})")
    report["rows"] = out
    if args.save:
        git = ["git", "rev-parse", "--short", "HEAD"]
        done = subprocess.run(git, capture_output=True, text=True, cwd=ROOT)  # noqa: S603, S607
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M")
        path = ROOT / "eval" / "results" / f"intents_{stamp}_{done.stdout.strip()}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"saved {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
