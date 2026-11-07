# Agent eval history

Each run of `python eval/run_agent_eval.py` appends one row. 22 questions (route, messy, adversarial), real LLM on fixed transport data with a scripted RER B disruption. Rules-only baseline in the same run. "Guard" = answers corrected after a retry / answers blocked and replaced by a template.

Changes to expectations are listed under the table, so scores stay comparable.

| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) | Cost / question | Guard | Results |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-08 00:28 | 70c1d03 | openai/gpt-4.1-mini | 32% | 82% | 6/7 | 1787 / 3450 ms | $0.00078 | 1 / 1 | [agent_2026-11-08_0028_70c1d03.json](results/agent_2026-11-08_0028_70c1d03.json) |
