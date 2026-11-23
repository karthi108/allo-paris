# Held-out agent eval

Questions in questions_agent_holdout.jsonl were written and committed before the first run. The code is never tuned against them: a failure here becomes a new dev-set question, never a fix aimed at this set.

| Date (UTC) | Commit | Model | Rules | Hybrid | Routes (hybrid) | p50 / p95 (hybrid) | Cost / question | Guard | Results |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-08 13:27 | 3b6cf57 | openai/gpt-4.1-mini | 53% | 73% | 0/3 | 352 / 4389 ms | $0.0008 | 1 / 1 | [agent_holdout_2026-11-08_1327_3b6cf57.json](results/agent_holdout_2026-11-08_1327_3b6cf57.json) |

Note on the first row: the judge passed a generic "could not verify" answer to a status question (judge bug, fixed after this run). Corrected hybrid score for that run: 10/15 (67%). See CHANGES.md.
| 2026-11-08 13:43 | d88cc56 | openai/gpt-4.1-mini | 40% | 80% | 3/4 | 2723 / 4125 ms | $0.00097 | 2 / 2 | [agent_holdout2_2026-11-08_1343_d88cc56.json](results/agent_holdout2_2026-11-08_1343_d88cc56.json) |

Note: the held-out set 2 row (d88cc56) is the quotable held-out result: 12/15 (80%), rules only 6/15 (40%).

Held-out set 3 (questions_agent_holdout3.jsonl, 92 questions, written 2026-11-23 by the assistant at the owner's request) was committed before its first run. Rows for it will say holdout3 in the Results file name.
| 2026-11-23 04:55 | 08a88e8 | openai/gpt-4.1-mini | 56% | 90% | 17/20 | 300 / 3376 ms | $0.00059 | 2 / 2 | [agent_holdout3_2026-11-23_0455_08a88e8.json](results/agent_holdout3_2026-11-23_0455_08a88e8.json) |

Note on the held-out set 3 row (08a88e8, first and only run, 2026-11-23 04:55 UTC): the judge said hybrid 83/92, rules only 52/92. Reading every answer: "le métro 6 à Bercy, il roule ?" was answered by the rules with a correct line 6 status, which the question accepts, but the judge only accepts a status from the AI path (judge bug, not fixed yet). Corrected: hybrid 84/92 (91.3%), rules only 53/92 (57.6%). This is the quotable held-out result. Details in CHANGES.md.
