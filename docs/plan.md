# Allô Paris · Project Plan (rev. 2)

AI voice phone line answering live Paris public transport questions from open data.
Owner: Karthikeyan. Solo, part-time alongside internship.
Goal: production-grade portfolio project for AI / voice / agent roles.

Last revised: 2026-11-03

---

## v1 sprint (1 day, 2026-11-05)
Working phone line first, hardening after. Scope cuts recorded in decisions.md D-009.
- [x] Reference data builder (arrets-lignes + arrets → stop areas)
- [x] Parser: line + fuzzy stop, FR/EN, clarifying questions
- [x] PRIM client: next departures + traffic, cache, feed-down handling
- [x] Template answers with freshness / scheduled labels
- [x] Twilio webhooks, signature check, caps, max duration, HMAC caller ID, 30-day purge
- [x] Live PRIM test (scripts/ask.py): departures + traffic OK, 224-1033 ms (2026-11-05)
- [ ] First real call; record p50/p95 from /stats
- [ ] 20-question manual check against the PRIM data

---

## Core principles

1. **Live data only.** Times, lines, availability come only from data sources. The LLM extracts intent and slots. It never produces facts.
2. **Deterministic rendering.** Answer text is built by templates from tool results. Any optional LLM rephrasing must pass the number/name validator (see Phase 2) or the template is used.
3. **Freshness is stated.** Every answer says whether it is real-time or scheduled, and how old the data is when relevant. If real-time is unavailable, say so and give the scheduled time.
4. **Exit criteria gate phases.** A phase is not started until the previous one meets its exit criteria. Dates are targets, exit criteria are commitments.
5. **Privacy by default.** No audio stored (by us or by processors). Caller numbers stored only as HMAC-SHA256 with a secret key. Transcripts auto-deleted after 30 days.
6. **AI disclosure.** The greeting says it is an AI assistant and that the service is unofficial.
7. **Abuse limits from day one.** Daily global call cap, per-caller rate limit, max call duration, outbound calling disabled.

---

## Stack

| Layer | Choice | Note |
|---|---|---|
| Language | Python 3.12+ | |
| API | FastAPI | WebSocket for media streams |
| Storage | Postgres | Redis only if a cache needs sharing across instances |
| STT | Speechmatics real-time | Verify FR/EN switching in one stream |
| TTS | To decide in Phase 0 spike | Compare latency and French quality |
| LLM | Provider-agnostic gateway | Small fast model for intent extraction |
| Telephony | Twilio or Telnyx | Bidirectional media streams, 8 kHz audio |
| Hosting | Always-on instance near Paris | Fly.io Paris region preferred; no sleeping free tiers |
| Observability | Sentry + structured logs + metrics | |
| CI | GitHub Actions | ruff, mypy, pytest |

---

## Data sources (verify access, licence, quotas before coding)

| Source | Use | Status |
|---|---|---|
| IDFM PRIM next departures | Real-time departures (partial network coverage) | To verify: quota, coverage list |
| IDFM static GTFS | Stops, stop areas, lines, directions, names | To verify: licence and attribution |
| IDFM traffic messages | Disruptions, line status | To verify |
| Vélib GBFS | Live bike / dock availability | To verify |
| PRIM journey planner | A→B (post-MVP only) | To verify availability |

Record findings in `docs/decisions.md` (D-series entries).

---

## Phase 0 · Setup + risk spike (Weeks 1-2)

**Day 1:** start the French phone number regulatory process with the telephony provider (identity / address documents). This blocks Phase 3.

Setup:
- Accounts: PRIM, telephony, Speechmatics, TTS, LLM.
- Budget caps and alerts on every paid service.
- Telephony: call recording OFF, outbound calling OFF, geo permissions restricted.
- Check processor retention / training settings (STT, TTS, LLM, telephony). Record in decisions.md.
- Repo skeleton, CI green.

**Risk spike (throwaway code, branch `spike/`):**
- One real call: number → media stream → STT → one hardcoded lookup ("next RER A at Châtelet") → TTS → caller.
- Measure per-step latency.
- Say 10 tricky stop names over the phone, log what STT returns.

EXIT:
- CI green, all keys working, budget alerts active.
- Spike call completes; latency numbers and STT stop-name results written in decisions.md.
- FR/EN language handling decided.

---

## Phase 1 · Data layer (Weeks 3-4)

- Clients: PRIM next departures, traffic messages, Vélib GBFS.
- GTFS loader: stop areas vs stop points, lines, directions/headsigns.
- Fuzzy stop resolver ("Chatelet" → Châtelet / Châtelet-Les Halles candidates with scores).
- Direction resolution: from question, or flagged as ambiguous.
- Per-source cache with `fetched_at`; refresh 30-60 s; respect quotas.
- One internal schema (`app/data/schema.py`): every result carries `source`, `fetched_at`, `realtime: bool`.
- Tests on recorded fixtures only (no live calls in CI).

EXIT: given stop + line + direction, returns next departures + freshness + realtime/scheduled flag, fully tested, including feed-down and stale-feed cases.

---

## Phase 2 · Text query engine (Weeks 5-6)

MVP intents:
1. Next departure (stop, line, direction)
2. Line status / disruptions
3. Vélib near a place

Pipeline: question → LLM (or rule matcher for top patterns) → intent JSON (Pydantic) → deterministic tool call → template render → validator.

- Clarifying question when stop, line or direction is ambiguous.
- Validator: every digit, time and line name in the output must appear in the tool payload. Fail → template fallback, logged.

Evals (all run in CI):
- **Intent/slot eval:** 150 questions FR + EN (synthetic, labelled as such) → expected intent JSON.
- **End-to-end eval:** question + frozen feed snapshot → expected answer.
- Metrics: intent accuracy, slot accuracy, answer correctness, validator rejection count, invented-data count (target 0, structural).

EXIT: evals in CI; invented-data count = 0; intent accuracy threshold set and met (set the number after the first baseline run).

---

## Phase 3 · Voice (Weeks 7-8)

- Inbound call → media stream WebSocket → streaming STT → query engine → TTS → caller.
- Barge-in.
- Latency budget per step, logged per call.
- Fallbacks: not understood, service unavailable, timeouts, feed down.
- FR + EN per Phase 0 decision.
- **Audio eval:** 50+ clips (own voice, friends, TTS with noise and accents, 8 kHz) → stop/line resolution accuracy.

EXIT: real phone call works end to end; p50 / p95 latency measured; audio eval baseline recorded.

---

## Phase 4 · Production hardening (Weeks 9-10)

- Deploy with health checks and auto-restart.
- Sentry + metrics: calls, completion rate, latency per step, errors per data source.
- Alerts: stale feed, error spike, budget threshold.
- Public status page: feed freshness + service status.
- Rate limit per HMAC caller ID, daily global cap, max call duration.
- Scheduled transcript deletion job + test proving deletion.
- Privacy page (what is stored, how long, which processors, pseudonymisation).
- `docs/threat-model.md` reviewed and controls verified.

EXIT: 7 days unattended without silent failures.

---

## Phase 5 · Paris launch + proof (Weeks 11-14)

- Beta: 20 people call with real questions. Add their questions (consented, anonymised) to the eval set.
- Measure: answer correctness, invented-data count, p50/p95 latency, completion rate, realtime vs scheduled share, audio stop-resolution accuracy.
- README: problem, live number, architecture diagram, decisions, results, limitations.
- 2-minute demo video.
- One write-up of a real failure and its fix.
- Production audit on the repo, fix P0/P1.

EXIT: public number + published measured results.

**This is the Definition of Done.**

---

## Post-launch, optional (only if time allows after job priorities)

- **A→B routing:** via PRIM journey planner, speak first leg + total duration only.
- **Proactive alerts:** explicit opt-in, SMS first; outbound calls only after a separate legal and fraud review.
- **More cities:** transport.data.gouv.fr real-time feeds; per-city config, eval, monitoring; each city passes its own eval before going live.
- **Channels:** web voice widget before WhatsApp (Meta approval + cost).

---

## Definition of Done

Public number live, Paris MVP intents covered, measured results published, monitored, documented, honest limitations stated.

## CV line (fill only with measured values)

> Built Allô Paris, a live AI voice line answering Paris transport questions from IDFM real-time open data: [X]% answer accuracy on [N] evaluated questions, 0 invented times across [N] evaluated questions and [N] production calls (deterministic answer rendering), [p50] s median response, [N] real calls handled.
