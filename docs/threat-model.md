# Threat Model

Scope: public inbound phone line, FastAPI backend, third-party processors (telephony, STT, TTS, LLM), open data feeds.
Method: asset → threat → control → verification. Status: `planned` · `implemented` · `verified`.

## Assets
- Service budget (telephony minutes, STT/TTS/LLM usage)
- Caller personal data (phone number, transcripts)
- API keys and secrets
- Answer integrity (correct times, no invented data)
- Service availability

## Trust boundaries
1. Caller ↔ telephony provider (untrusted input: audio)
2. Telephony provider ↔ our webhook / WebSocket (must be authenticated)
3. Our backend ↔ processors (STT, TTS, LLM)
4. Our backend ↔ open data feeds (untrusted, may be stale or malformed)

## Threats and controls

| # | Threat | Impact | Control | Verification | Status |
|---|---|---|---|---|---|
| T1 | Cost attack: repeated or long calls | Budget drain | Per-caller rate limit (HMAC ID), daily global cap, max call duration, provider budget alerts | Load test with scripted calls; alert fires | planned |
| T2 | Toll fraud via outbound calling | Large bill | Outbound disabled at provider; geo permissions restricted | Attempted outbound fails | planned |
| T3 | Spoofed webhook / WebSocket | Fake calls, cost, data injection | Validate provider request signatures; reject unsigned | Unsigned request test returns 403 | planned |
| T4 | Voice prompt injection ("ignore instructions") | Off-topic or harmful output | LLM output is schema-validated intent JSON only; deterministic rendering; unknown intent → fixed reply | Injection phrases in eval set map to `unknown` | planned |
| T5 | Invented or wrong data spoken | User misses a train; trust loss | Deterministic templates; output validator; freshness stated; stale threshold → "real-time unavailable" | Eval invented-data count = 0; stale fixture test | planned |
| T6 | Malformed / stale feed data | Wrong answers, crash | Schema validation on ingest; `fetched_at` checks; per-source circuit breaker | Fixture tests for malformed + stale | planned |
| T7 | Caller number exposure | GDPR breach | HMAC-SHA256 with secret key; raw number never logged | Log scan test; unit test on hashing | planned |
| T8 | Transcript over-retention | GDPR breach | Scheduled 30-day deletion; DB-level check | Test inserts old row, job deletes it | planned |
| T9 | Processor retains audio | Breaks "no audio stored" claim | Retention/training settings checked and disabled per processor | Recorded in decisions.md with date | planned |
| T10 | Secret leak | Account takeover, cost | Env vars from secret manager; `.env` gitignored; secret scanning in CI | CI secret scan step | planned |
| T11 | Caller enumeration / data access | Privacy breach | No caller-facing data lookup; no personal data in answers | Design review | planned |
| T12 | Dependency compromise | Code execution | Pinned dependencies, Dependabot, minimal deps | CI audit step | planned |

## Out of scope (stated limitations)
- Telephony network-level attacks (provider responsibility)
- Caller ID spoofing defeating per-caller limits (global cap is the backstop)
