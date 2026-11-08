# Agent eval history

Each run of `python eval/run_agent_eval.py` appends one row. 22 questions (route, messy, adversarial), real LLM on fixed transport data with a scripted RER B disruption. Rules-only baseline in the same run. "Guard" = answers corrected after a retry / answers blocked and replaced by a template.

Changes to expectations are listed under the table, so scores stay comparable.

| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) | Cost / question | Guard | Results |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-07 23:28 | 70c1d03 | openai/gpt-4.1-mini | 32% | 82% | 6/7 | 1787 / 3450 ms | $0.00078 | 1 / 1 | [agent_2026-11-08_0028_70c1d03.json](results/agent_2026-11-08_0028_70c1d03.json) |
| 2026-11-07 23:37 | f5e0499 | openai/gpt-4.1-mini | 32% | 86% | 7/7 | 2026 / 3502 ms | $0.00091 | 1 / 1 | [agent_2026-11-07_2337_f5e0499.json](results/agent_2026-11-07_2337_f5e0499.json) |
| 2026-11-07 23:56 | 22799de | openai/gpt-4.1-mini | 32% | 100% | 7/7 | 2237 / 3331 ms | $0.00103 | 2 / 1 | [agent_2026-11-07_2356_22799de.json](results/agent_2026-11-07_2356_22799de.json) |
| 2026-11-08 13:28 | 3b6cf57 | openai/gpt-4.1-mini | 32% | 82% | 5/7 | 3056 / 3770 ms | $0.00117 | 2 / 1 | [agent_2026-11-08_1328_3b6cf57.json](results/agent_2026-11-08_1328_3b6cf57.json) |
