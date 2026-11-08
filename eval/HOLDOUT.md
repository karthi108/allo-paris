# Held-out agent eval

Questions in questions_agent_holdout.jsonl were written and committed before the first run. The code is never tuned against them: a failure here becomes a new dev-set question, never a fix aimed at this set.

| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) | Cost / question | Guard | Results |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-08 13:27 | 3b6cf57 | openai/gpt-4.1-mini | 53% | 73% | 0/3 | 352 / 4389 ms | $0.0008 | 1 / 1 | [agent_holdout_2026-11-08_1327_3b6cf57.json](results/agent_holdout_2026-11-08_1327_3b6cf57.json) |

Note on the first row: the judge passed a generic "could not verify" answer to a status question (judge bug, fixed after this run). Corrected hybrid score for that run: 10/15 (67%). See CHANGES.md.
| 2026-11-08 13:43 | d88cc56 | openai/gpt-4.1-mini | 40% | 80% | 3/4 | 2723 / 4125 ms | $0.00097 | 2 / 2 | [agent_holdout2_2026-11-08_1343_d88cc56.json](results/agent_holdout2_2026-11-08_1343_d88cc56.json) |

Note: the held-out set 2 row (d88cc56) is the quotable held-out result: 12/15 (80%), rules only 6/15 (40%).
