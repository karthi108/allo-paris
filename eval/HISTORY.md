# Agent eval history

Each run of `python eval/run_agent_eval.py` appends one row. 22 questions (route, messy, adversarial), real LLM on fixed transport data with a scripted RER B disruption. Rules-only baseline in the same run. "Guard" = answers corrected after a retry / answers blocked and replaced by a template.

Changes to expectations are listed under the table, so scores stay comparable.

| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) | Cost / question | Guard | Results |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-07 23:28 | 70c1d03 | openai/gpt-4.1-mini | 32% | 82% | 6/7 | 1787 / 3450 ms | $0.00078 | 1 / 1 | [agent_2026-11-08_0028_70c1d03.json](results/agent_2026-11-08_0028_70c1d03.json) |
| 2026-11-07 23:37 | f5e0499 | openai/gpt-4.1-mini | 32% | 86% | 7/7 | 2026 / 3502 ms | $0.00091 | 1 / 1 | [agent_2026-11-07_2337_f5e0499.json](results/agent_2026-11-07_2337_f5e0499.json) |
| 2026-11-07 23:56 | 22799de | openai/gpt-4.1-mini | 32% | 100% | 7/7 | 2237 / 3331 ms | $0.00103 | 2 / 1 | [agent_2026-11-07_2356_22799de.json](results/agent_2026-11-07_2356_22799de.json) |
| 2026-11-08 13:28 | 3b6cf57 | openai/gpt-4.1-mini | 32% | 82% | 5/7 | 3056 / 3770 ms | $0.00117 | 2 / 1 | [agent_2026-11-08_1328_3b6cf57.json](results/agent_2026-11-08_1328_3b6cf57.json) |
| 2026-11-08 13:33 | fd728f1 | openai/gpt-4.1-mini | 35% | 96% | 7/7 | 2986 / 3618 ms | $0.00109 | 2 / 1 | [agent_2026-11-08_1333_fd728f1.json](results/agent_2026-11-08_1333_fd728f1.json) |
| 2026-11-08 13:36 | a174c6b | openai/gpt-4.1-mini | 35% | 96% | 7/7 | 1834 / 4062 ms | $0.00107 | 1 / 1 | [agent_2026-11-08_1336_a174c6b.json](results/agent_2026-11-08_1336_a174c6b.json) |
| 2026-11-08 13:57 | 95210ef | openai/gpt-4.1-mini | 33% | 100% | 7/7 | 3062 / 4337 ms | $0.00113 | 1 / 0 | [agent_2026-11-08_1357_95210ef.json](results/agent_2026-11-08_1357_95210ef.json) |
| 2026-11-08 13:57 | 95210ef (uncommitted changes) | openai/gpt-4.1-mini | 33% | 100% | 7/7 | 2752 / 3686 ms | $0.00112 | 1 / 0 | [agent_2026-11-08_1357_95210ef-dirty.json](results/agent_2026-11-08_1357_95210ef-dirty.json) |
| 2026-11-08 13:59 | 95210ef (uncommitted changes) | openai/gpt-4.1-mini | 33% | 96% | 7/7 | 3126 / 3862 ms | $0.00113 | 1 / 0 | [agent_2026-11-08_1359_95210ef-dirty.json](results/agent_2026-11-08_1359_95210ef-dirty.json) |
| 2026-11-23 05:01 | fb0a44e | openai/gpt-4.1-mini | 25% | 81% | 7/8 | 1281 / 3731 ms | $0.00092 | 2 / 0 | [agent_2026-11-23_0501_fb0a44e.json](results/agent_2026-11-23_0501_fb0a44e.json) |
| 2026-11-23 05:13 | a042807 | openai/gpt-4.1-mini | 38% | 94% | 7/8 | 1050 / 4071 ms | $0.00095 | 2 / 0 | [agent_2026-11-23_0513_a042807.json](results/agent_2026-11-23_0513_a042807.json) |
| 2026-11-23 05:23 | 1d3f1bc | openai/gpt-4.1-mini | 38% | 100% | 8/8 | 2168 / 3819 ms | $0.00107 | 3 / 0 | [agent_2026-11-23_0523_1d3f1bc.json](results/agent_2026-11-23_0523_1d3f1bc.json) |
| 2026-11-23 09:15 | aa7014f | openai/gpt-4.1-mini | 43% | 95% | 8/8 | 1924 / 4926 ms | $0.00113 | 5 / 1 | [agent_2026-11-23_0915_aa7014f.json](results/agent_2026-11-23_0915_aa7014f.json) |
| 2026-11-23 09:37 | 74bd867 | openai/gpt-4.1-mini | 44% | 96% | 8/8 | 1854 / 4592 ms | $0.00115 | 5 / 1 | [agent_2026-11-23_0937_74bd867.json](results/agent_2026-11-23_0937_74bd867.json) |
