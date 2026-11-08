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

## D-014 · Vélib' from Paris open data, not the operator's GBFS
- **Status:** accepted
- **Date:** 2026-11-07
- **Context:** The operator GBFS URL returned a Cloudflare bot check (HTTP 403) when tested.
- **Decision:** Use the City of Paris Opendatasoft dataset `velib-disponibilite-en-temps-reel` with a server-side distance query (500 m, 3 nearest). No key, cache 60 s, daily budget 2000.
- **Consequences:** Station reports can be old; answers flag stations not updated for more than 30 minutes.

## D-015 · Name what v1 cannot do
- **Status:** accepted
- **Date:** 2026-11-07
- **Context:** A phrase test showed journeys ("comment aller de A à B"), future times and buses were silently answered as a next-departure question for the first station heard.
- **Decision:** Detect them and reply with a fixed "not supported yet" message. Airports without a name get a clarifying question.

## D-016 · Offline eval on the full station list
- **Status:** accepted
- **Date:** 2026-11-07
- **Decision:** `eval/questions.jsonl` (FR/EN, labelled synthetic) run against a snapshot of the real IDFM station list with a fixed fake data source. Metrics: intent, line and station accuracy, invented numbers. Runs in CI with thresholds (95% accuracy, 0 invented numbers).
- **Found by the eval:** equal-score ties picked the shortest name ("Palaiseau" for "Massy Palaiseau"); fixed by preferring the name covering more words.

## D-017 · Free hosting on Render
- **Status:** proposed (config in `render.yaml`, not deployed yet)
- **Decision:** Free web service, Frankfurt. Liveness `/healthz` for the host; `/health` returns 503 when the PRIM feed fails, for an external uptime monitor.
- **Trade-off:** free instances sleep; acceptable for a portfolio demo, stated in the README.

## D-018 · Hybrid: rules first, LLM agent with tools, grounding guard
- **Status:** accepted
- **Date:** 2026-11-07
- **Context:** A rules-only eval scored 3/22 on route, messy and adversarial questions. Routes and free phrasing need language understanding; times must stay trustworthy.
- **Decision:** Rules answer when confident. Otherwise an LLM agent (OpenAI or Anthropic, plain HTTP, tool calling) uses five tools over the existing data layer. A grounding guard checks every number and line in the draft against tool outputs: one corrective retry, then a deterministic template.
- **Why not LLM-only:** cost and latency on the common questions, and determinism where it matters.
- **Controls:** daily USD cap, max 5 tool rounds, no free-text tool, provider errors fall back to rules.

## D-019 · Routes from IDFM's official planner, disruption-aware
- **Status:** accepted (endpoint to confirm with `scripts/check_routes.py`)
- **Date:** 2026-11-07
- **Decision:** `plan_route` calls PRIM Navitia journeys (data_freshness=realtime) and attaches current traffic messages for every line used. The agent is instructed to prefer a journey that avoids a disrupted line, and the agent eval checks it does.
- **Quota:** 1,000/day for new PRIM accounts (PRIM page); our cap 300/day.

## D-020 · Deterministic refusals before the AI
- **Status:** accepted
- **Date:** 2026-11-07
- **Decision:** Prompt-injection phrasing, fares and buses are answered by fixed templates and never reach the LLM or data APIs. Found by the agent eval baseline (fares were answered with a list of lines).

---

## Data source verification (fill in Phase 0)

| Source | Access | Licence / attribution | Quota | Real-time coverage | Verified on |
|---|---|---|---|---|---|
| PRIM next departures | apikey header (community code; confirm) | | 1000/day for new accounts (third-party claim; confirm) | partial | |
| IDFM arrets-lignes / arrets / zones-d-arrets | open, Opendatasoft API | | | n/a | 2026-11-05 (fields verified) |
| IDFM traffic messages (general-message) | PRIM key | IDFM PRIM | shared 900/day budget (ours) | live | 2026-11-05 (live answers) |
| Vélib (Paris open data) | open, no key | Ville de Paris open data | daily budget 2000 (ours) | live station reports | 2026-11-07 (fields verified) |

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

## D-021 · EV charger layer: Belib' first, public data only (2026-11-08)
- Public open data only: no private, employer or internal data, rules or knowledge. Operators are anonymised in any ranking.
- First source: Belib' real-time status (City of Paris open data). Verified 2026-11-08: one export call returns all 2,036 charge points at 398 addresses, five status values, no API key.
- The meaning of last_updated is not assumed: every snapshot measures it. Result on 2026-11-08 (two snapshots 3 min apart, 34 changes): 3 points had a new last_updated with the same status, 2 changed status with the same last_updated. So last_updated is not a reliable change time; durations come from the collector's own observed history.
- The plain export URL returned copies up to 22 minutes old to the collector. Fixed with a unique URL per request; snapshots whose newest last_updated does not move for 5 minutes are marked stale and ignored by detection.
- IRVE dynamique (national, per operator) comes after Belib', once coverage in Paris is checked.
- No ML, no LLM in detection: fixed rules over the status history; the LLM only answers questions through tools.

## D-022 · Collector runs on GitHub Actions, data in an ev-data branch as CSV (2026-11-08)
- Free and 24/7: the repo is public, so scheduled Actions cost nothing. A home PC would leave gaps at night.
- Every 10 minutes (cron */10). GitHub may delay or skip scheduled runs; snapshots.csv records real coverage, so reports show measured uptime, not assumed uptime.
- CSV, not SQLite, in git: text diffs stay small; committing a binary database 144 times a day would bloat the repo.
- The ev-data branch holds data only. CI runs on main and pull requests only.
- A failed fetch or a stale feed fails the run (visible in Actions); a stale snapshot is still written so the gap is on record.

## D-023 · Reliability rules R1-R4, thresholds set from data (2026-11-08)
- R1 stuck out of service, R2 ghost available (only when another point at the same address was used), R3 flapping (normal charging sessions ignored), R4 silent operator data. Defined in app/ev/rules.py.
- Durations count only time the collector observed; gaps and stale snapshots are excluded, never read as "stuck" or "fine".
- Starting thresholds (24 h, 72 h, 6 changes/h, 7 days) are provisional. After 7 days of collection they are set from the observed distributions and the reasoning is recorded here.
- Fixed rules, not ML or an LLM: testable, explainable, free per check.
- 2026-11-08: the "*/10" schedule produced no scheduled run in 1 h 40 min after the push (manual runs worked). Changed to "3-59/10" (off the busy start of the hour) and re-pushed, which also re-registers the schedule. If runs still do not appear, an external trigger is the fallback.
