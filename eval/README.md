# Evals

| Eval | Input | Expected | Runs in CI |
|---|---|---|---|
| `intents` | Text question (FR/EN) | Intent JSON | yes |
| `e2e` | Question + frozen feed snapshot in `fixtures/` | Rendered answer | yes |
| `audio` | 8 kHz clip | Resolved stop + line | manual (Phase 3) |

Rules:
- Label each question `synthetic` or `beta` (consented, anonymised).
- Include injection attempts; expected intent is `unknown`.
- Never store real caller audio here.
