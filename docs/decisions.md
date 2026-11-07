# Decisions Log

Format: one entry per decision. Status: `proposed` · `accepted` · `superseded`.
Never delete an entry; mark it superseded and link the replacement.

---

## D-001 · LLM extracts intent only; answers are rendered deterministically
- **Status:** accepted
- **Date:** 2026-11-03
- **Context:** The core risk of an AI transport line is a confident wrong time.
- **Decision:** The LLM returns a Pydantic-validated intent + slots object. Tools fetch data. Templates render the answer. Optional LLM rephrasing must pass a validator: every digit, time and line name in the output must exist in the tool payload, otherwise the template is used.
- **Consequences:** Invented data is prevented by construction, not by prompting. Answers are less "chatty". Evals focus on parsing accuracy.

## D-002 · Caller identity stored as HMAC-SHA256, not plain hash
- **Status:** accepted
- **Date:** 2026-11-03
- **Context:** French phone numbers form a small space; a plain SHA-256 can be reversed by brute force.
- **Decision:** `HMAC-SHA256(secret_key, E.164 number)`. Key in secret manager, never in repo. Key rotation invalidates rate-limit history, which is acceptable.
- **Consequences:** Data is pseudonymised (still personal data under GDPR), stated as such on the privacy page.

## D-003 · Risk spike before the data layer
- **Status:** accepted
- **Date:** 2026-11-03
- **Context:** Phone latency and French stop-name STT accuracy are the two most likely project killers.
- **Decision:** Phase 0 includes a throwaway end-to-end call with one hardcoded lookup.
- **Consequences:** Spike code is not merged to main.

## D-004 · MVP intents limited to 3
- **Status:** accepted
- **Date:** 2026-11-03
- **Decision:** Next departure, line status/disruptions, Vélib near a place. A→B routing deferred (long spoken itineraries are hard to follow; would duplicate a journey planner).

## D-005 · Hosting region
- **Status:** proposed
- **Decision:** Always-on instance near Paris (Fly.io Paris region preferred). No sleeping free tier (breaks first-call WebSocket latency).
- **To verify:** pricing, WebSocket support, health checks.

## D-006 · Telephony provider
- **Status:** proposed
- **Options:** Twilio, Telnyx.
- **Criteria:** French number requirements and lead time, bidirectional media stream support, price per inbound minute, ability to disable recording and outbound.
- **Result:** _fill after Phase 0_

## D-007 · FR/EN language handling
- **Status:** proposed
- **Options:** (a) STT auto-detect / multilingual stream if supported, (b) bilingual greeting with "say English to switch".
- **Result:** _fill after Phase 0 spike_

## D-008 · TTS provider
- **Status:** proposed
- **Criteria:** time to first audio byte, French naturalness, stop-name pronunciation, 8 kHz output, cost, data retention.
- **Result:** _fill after Phase 0 spike_

## D-009 · v1 ships without an LLM, Speechmatics or media streams
- **Status:** accepted
- **Date:** 2026-11-05
- **Context:** Goal is a working phone line in 1 day.
- **Decision:** Twilio `<Gather input="speech">` for speech-to-text, `<Say>` for voice, deterministic parser (regex for lines + fuzzy stop matching) instead of an LLM. SQLite instead of Postgres. Dataclasses instead of Pydantic.
- **Consequences:** ~2-3 s latency, no barge-in, rigid phrasing. Zero LLM cost and zero hallucination surface. v2 replaces STT/TTS with streaming and adds an LLM only for questions the parser can't handle.

## D-010 · Query PRIM by stop area, filter by line
- **Status:** accepted
- **Date:** 2026-11-05
- **Context:** arrets-lignes gives metro stops as quays (IDFM:<arrid>) and RER stops as stop areas (IDFM:monomodalStopPlace:<zdaid>).
- **Decision:** Map quays to their zdaid via the `arrets` dataset, query `STIF:StopArea:SP:<zdaid>:`, filter results on LineRef (PRIM doc: multi-line stops must be filtered on LineRef). Group answers by destination so direction never needs a clarifying question.

## D-011 · Traffic messages via SIRI general-message
- **Status:** proposed (unverified against live API)
- **Decision:** `marketplace/general-message?LineRef=STIF:Line::<id>:`. If it fails live, switch to the PRIM "Traffic Info Messages" (line_reports) API.

## D-012 · Web companion on the same backend
- **Status:** accepted
- **Date:** 2026-11-05
- **Decision:** One FastAPI app serves the phone webhooks and a web page (Leaflet + OSM map, ask box, live boards). The web API reuses the dialog and templates, so the no-invented-data guarantee holds on both channels.
- **Controls:** shared PRIM daily budget (quota protection), per-IP rate limit, CSP header, no HTML built from data (textContent only), per-session clarification state capped at 1000.
- **Why:** recruiters can try it from a link; the phone line stays the differentiator.

## D-013 · Web redesign: own identity, transit-app patterns
- **Status:** accepted
- **Date:** 2026-11-05
- **Decision:** Full-screen map with greyscale base tiles (CSS filter on OSM, no extra provider), floating card on desktop / bottom sheet on mobile, station autocomplete (client-side over 1039 stop areas), board grouped by direction, disruption banner, Near me (browser geolocation, nothing sent to server), favourites in localStorage.
- **Not copied:** no Navigo / IDFM / RATP logos, fonts or pictograms. Line badges use own shapes per mode with colours from IDFM open data.
- **Quota:** disruption messages cached 5 min server-side (they change slowly).

---

## Data source verification (fill in Phase 0)

| Source | Access | Licence / attribution | Quota | Real-time coverage | Verified on |
|---|---|---|---|---|---|
| PRIM next departures | apikey header (community code; confirm) | | 1000/day for new accounts (third-party claim; confirm) | partial | |
| IDFM arrets-lignes / arrets / zones-d-arrets | open, Opendatasoft API | | | n/a | 2026-11-05 (fields verified) |
| IDFM traffic messages | | | | | |
| Vélib GBFS | | | | | |

## Processor data handling (fill in Phase 0)

| Processor | Audio/text retained? | Used for training? | Setting changed | Verified on |
|---|---|---|---|---|
| Telephony | | | Recording OFF | |
| Speechmatics | | | | |
| TTS | | | | |
| LLM | | | | |

## Spike results (fill in Phase 0)

| Step | p50 ms | p95 ms | Notes |
|---|---|---|---|
| STT final | | | |
| Intent | | | |
| Data fetch | | | |
| TTS first byte | | | |
| End to end | | | |

| Spoken stop name | STT output | Correct? |
|---|---|---|
| Château d'Eau | | |
| Château Rouge | | |
| Saint-Michel Notre-Dame | | |
| Châtelet-Les Halles | | |
| Saint-Lazare | | |
| La Défense | | |
| Porte de Clignancourt | | |
| Bibliothèque François Mitterrand | | |
| Charles de Gaulle - Étoile | | |
| Gare du Nord | | |
