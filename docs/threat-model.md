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
| T1 | Cost attack: repeated or long calls | Budget drain | Per-caller rate limit (HMAC ID), daily global cap, max call duration, provider budget alerts | Unit tests for per-caller and global caps, max duration | implemented |
| T2 | Toll fraud via outbound calling | Large bill | Outbound disabled at provider; geo permissions restricted | Attempted outbound fails | planned |
| T3 | Spoofed webhook / WebSocket | Fake calls, cost, data injection | Validate provider request signatures; reject unsigned | Signature round-trip and tamper tests | implemented |
| T4 | Prompt injection by voice or text | Off-topic output, false claims | Injection phrasing refused by rules before the LLM; LLM limited to 5 tools; grounding guard blocks values not returned by tools; system prompt tells the model to ignore rule changes | Tests: injection refused with no data or AI call; agent eval adversarial set | verified (rules), eval pending (AI) |
| T5 | Invented or wrong data spoken | User misses a train; trust loss | Deterministic templates; output validator; freshness stated; stale threshold → "real-time unavailable" | Eval invented numbers = 0 (CI); stale and feed-down tests | verified |
| T6 | Malformed / stale feed data | Wrong answers, crash | Schema validation on ingest; `fetched_at` checks; per-source circuit breaker | Malformed payload and stale tests | implemented |
| T7 | Caller number exposure | GDPR breach | HMAC-SHA256 with secret key; raw number never logged | Test: raw number absent from DB dump; hashing tests | verified |
| T8 | Transcript over-retention | GDPR breach | Scheduled 30-day deletion; DB-level check | Tests for purge on write and background purge | verified |
| T9 | Processor retains audio | Breaks "no audio stored" claim | Retention/training settings checked and disabled per processor | Recorded in decisions.md with date | planned |
| T10 | Secret leak | Account takeover, cost | Env vars from secret manager; `.env` gitignored; secret scanning in CI | gitleaks full-history scan in CI | verified |
| T11 | Caller enumeration / data access | Privacy breach | No caller-facing data lookup; no personal data in answers | Design review | planned |
| T12 | Dependency compromise | Code execution | Pinned dependencies, Dependabot, minimal deps | CI audit step | planned |

## AI-specific controls
| # | Threat | Control | Status |
|---|---|---|---|
| A1 | Hallucinated times, lines or durations | Grounding guard on every AI answer; retry then template | implemented, tested |
| A2 | Runaway cost | Daily USD cap checked before every call; rules path when reached | implemented, tested |
| A3 | Tool misuse / loops | Fixed tool list, max 5 rounds, unknown tools return errors | implemented, tested |
| A4 | Provider outage | Falls back to rules; counted on /metrics | implemented, tested |
| A5 | Data sent to the LLM provider | Question text and tool results only; no caller number, no location | by design; stated on /privacy |

## Web-specific controls
| # | Threat | Control | Status |
|---|---|---|---|
| W1 | PRIM quota exhaustion by web traffic | Shared daily budget (900), per-IP rate limit (20/min), caching | implemented |
| W2 | XSS through data (station names, messages) | DOM built with textContent only; CSP header | implemented |
| W3 | Location privacy | Near me computed client-side only | implemented |
| W4 | Third-party exposure | OSM tiles and cdnjs see visitor IP; stated on /privacy | documented |

## Out of scope (stated limitations)
- Telephony network-level attacks (provider responsibility)
- Caller ID spoofing defeating per-caller limits (global cap is the backstop)
