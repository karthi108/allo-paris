# Evals

| Eval | Input | Checks | Runs in CI |
|---|---|---|---|
| `run_eval.py` | `questions.jsonl` on `data/stops_snapshot.json` (full IDFM station list) | intent, line, station, invented numbers | yes (`--check`) |
| `../scripts/measure.py` | 20 questions against live PRIM, cache off | p50 / p95 latency, feed errors | no (needs API key) |
| audio | 8 kHz clips | stop/line resolution | not yet (phone line not live) |

Rules:
- Each question is labelled `synthetic` (written by the author) or `beta` (real user, consented, anonymised).
- Injection attempts are included; expected intent is `unknown`.
- `stop`/`line` set to `null` means "not checked" for that question.
- Thresholds: 95% intent / line / station accuracy and 0 invented numbers, or CI fails.
- Never store real caller audio here.

Snapshot: `data/stops_snapshot.json` is derived from IDFM open data (arrets-lignes, arrets, referentiel-des-lignes), 2026-11-07.
