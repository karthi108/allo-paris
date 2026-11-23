# Allô Paris

A hybrid AI assistant for getting around Paris: deterministic rules for the common questions, an LLM agent with tool calling for everything else, and a grounding guard that blocks any number, line or status the data sources did not return. Transport (metro, RER, tram, Transilien), Vélib' bikes and Belib' public EV chargers, with a charger reliability layer built from 24/7 collection of open data.

> Independent project using public open data only (IDFM PRIM, Ville de Paris). Not affiliated with or endorsed by Île-de-France Mobilités, RATP or the City of Paris.

**Status (2026-11-08):** web app and AI agent working on live data · EV charger collector running every 10 min since 2026-11-08, reliability thresholds provisional until 7 days of data · phone line built, not yet tested on a real call · not yet deployed publicly · see [plan](docs/plan.md).

## What it does
- **Next departures** for metro, RER, tram and Transilien: "prochain RER A à Châtelet", "la 13 à Saint-Lazare", "line four at chateau rouge"
- **Disruptions:** "perturbations RER B", "any delays on line 4"
- **Vélib' nearby:** "Vélib à Bastille", "any bikes near the Eiffel Tower" (bikes, e-bikes, free docks)
- **Landmarks:** Eiffel Tower, Louvre, Sacré-Cœur, airports, Disneyland… mapped to the nearest station, typos tolerated
- **Routes (AI agent + IDFM's official journey planner):** "fastest way from Gare du Nord to the Eiffel Tower", "demain à 8h de Nation à La Défense"; checks live disruptions on every line of the journey and recommends the alternative when one is disrupted
- **EV chargers (Belib', City of Paris network):** "y a une borne qui marche près du Panthéon ?", "EV chargers near Bastille" → live status per address (free, charging, out of service) plus reliability warnings from the observed history; searches by station or by street/landmark
- **Asks back** when the origin, line or station is missing or ambiguous; **declines** what it doesn't cover (fares, buses) and refuses prompt-injection attempts
- **Web app:** full-screen map of 979 stations, search with autocomplete, boards grouped by direction (30 s refresh), disruption banner, Vélib nearby, Near me, favourites, mic input and read-aloud, FR/EN, light/dark, mobile bottom sheet

## How it answers
```
question ─► injection filter ─► rules parser ──── confident? ──► template answer        (free, ~76 ms)
                                     │ no
                                     ▼
                         LLM agent (OpenAI or Anthropic, tool calling)
                           find_station · next_departures · line_status
                           velib_nearby · chargers_nearby · plan_route (IDFM planner + live disruptions)
                                     │ draft answer
                                     ▼
                         grounding guard: every number and line must be in tool results;
                         "it's running" needs a successful data result; task checks
                         (time asked → time used, origin given → not asked again)
                           pass ─► answer      fail ─► 1 retry ─► fail ─► safe template
```
- **Rules first:** most questions never reach the LLM: zero cost, deterministic, fast.
- **The LLM only understands and phrases.** Times, lines and routes come from tools over live data; the guard rejects anything else. See [D-001](docs/decisions.md), [D-018](docs/decisions.md).
- **Graceful degradation:** no key, budget cap reached or provider down → the rules path keeps working.
- **Public live metrics** at `/metrics`: share of questions needing the AI, latency per path, guard corrections and blocks, AI cost today. Aggregates only, no question text.

## Results (measured)
Every number below comes from a script in this repo; raw results with tool traces are in [eval/results](eval/results).

**AI agent: how it is evaluated.** Real LLM (`openai/gpt-4.1-mini`), fixed fake transport data with a scripted RER B disruption, so runs are reproducible and use no PRIM quota. Two kinds of question sets:
- **Dev set** ([questions_agent.jsonl](eval/questions_agent.jsonl), now 52 questions): the system was improved against it, so it measures stability, not general accuracy.
- **Held-out sets**: committed to git **before** their first run and never tuned against; a held-out failure becomes a new dev question with different wording, never a targeted fix. Each set is blind for one run only; the first run is the quoted number.
- **Who wrote the questions:** every held-out question was written by the AI assistant used to build this project (Claude), at the owner's request. None comes from the owner or from real users, so these are synthetic tests, not real-traffic accuracy.

Checks on every answer: right tools and stations, origin and time respected, the journey that avoids the disruption recommended first, at most 3 sentences (answers are read aloud), no invented numbers; for document answers, a citation of the right document and "no document" (without citation) when the corpus does not cover the topic. Every answer of every held-out run was also read by hand. History and every change to the judge: [eval/HISTORY.md](eval/HISTORY.md), [eval/HOLDOUT.md](eval/HOLDOUT.md), [eval/CHANGES.md](eval/CHANGES.md).

| Held-out set (first and only blind run) | Rules only | Hybrid (rules + AI) | Cost / question | Hybrid p50 / p95 |
|---|---|---|---|---|
| **Set 3**, 92 questions FR/EN: routes, departures, status, Vélib', EV, typos, slang, tricks (08a88e8, 2026-11-23) | 53/92 (57.6%) | **84/92 (91.3%)** | $0.00059 | 300 / 3376 ms |
| **Set 4**, 32 RAG questions: station accessibility, official fiches, topics outside the corpus (81d3050, 2026-11-23) | 19/32 (59.4%) | **23/32 (71.9%)** | $0.00064 | 1688 / 2820 ms |
| Set 2, 15 questions (d88cc56, 2026-11-08) | 6/15 (40%) | 12/15 (80%) | $0.00097 | 2723 / 4125 ms |

- **Set 3:** the judge said 83/92 and 52/92; reading the answers found one judge bug (a correct rules-path line status was rejected), so both scores are +1. 7 of the 8 real failures are the rules answering confidently when they should hand over to the AI; two of those give wrong departure times (a fake station fuzzy-matched to a real one, a typo origin).
- **Set 4 (RAG v1, BM25):** accessibility 11/14, fiche questions 9/12, tricks 3/6. Failures include two confident wrong rules answers ("vélo dans le RER" read as Vélib', "Cité U" matched to Cité), the AI answering a dog question from general knowledge without a document, wrong passages retrieved from a long fiche, and one citation pointing to the wrong fiche.
- **After each run** the failures became new dev questions and generic fixes; both sets are no longer blind. Latest dev run (74bd867, 52 questions): 51/52 on reading (judge 50/52), $0.00115 per question, hybrid p50 / p95 1854 / 4592 ms. A new held-out set is needed before quoting a post-fix number.

**Rules path** (no AI):

| Metric | Value | How |
|---|---|---|
| Intent / line / station accuracy | **61/61 (100%)** | `python eval/run_eval.py`, synthetic FR/EN questions on the full IDFM station list |
| Invented numbers in answers | **0** | same eval checks every number against data source, templates and names |
| Answer latency p50 / p95 | **76 ms / 311 ms** | `python scripts/measure.py`: 20 live questions, cache off, 2026-11-07 |
| Tests | **218 passing** | `pytest`, in CI with ruff, mypy strict and gitleaks |

The eval questions are synthetic (written by the author and the assistant), not real user traffic.

## EV charger reliability (Belib')
Public open data only: the Belib' real-time feed of the City of Paris (2,036 charge points at 398 addresses on 2026-11-08). No private, employer or internal data; operators would be anonymised in any ranking.

```
cron-job.org (every 10 min) ─► GitHub Actions ─► Belib' export (1 request, cache-proof URL)
   ─► status changes as CSV on the ev-data branch ─► rules R1-R4 ─► flags.json ─► app + AI tool
```
- **Rules, not ML or an LLM:** R1 stuck out of service · R2 "available" but never used while neighbours are · R3 flapping · R4 operator data silent for days. Fixed code with tests, explainable flags ("unknown since Tue 14:20, 31 h observed").
- **Measured, not assumed:** the feed's `last_updated` turned out not to be a reliable change time (both "new time, same status" and "new status, same time" seen within minutes), so durations come from the collector's own observations. A cached copy 22 minutes old was detected once; stale snapshots are flagged and ignored.
- **Gaps are never data:** durations count only time actually observed; collection gaps and stale snapshots are excluded and reported.
- **First result:** 40 points with no operator update for more than 7 days, e.g. all 3 points at Place du Panthéon "unknown" since June 2026.
- **Thresholds are provisional** (24 h, 72 h, 6 changes/h, 7 days) until set from 7 days of collected data. Decisions: [D-021 to D-023](docs/decisions.md).
- Report: `python scripts/ev_report.py --data <ev-data checkout>`.

## Run locally (Windows, PowerShell)
```powershell
cd "K:\AI\Allo Paris"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env          # set ALLO_PRIM_API_KEY and ALLO_CALLER_HMAC_KEY
python scripts\build_stops.py   # downloads the IDFM station list (~1 min)
.\dev.ps1                       # tests, then server on http://127.0.0.1:8000 (auto-reload)
```
Other commands: `python scripts\ask.py "ligne 4 Gare du Nord"` or `python scripts\ask.py --en "EV chargers near Bastille"` (live answer in the terminal) · `python eval\run_eval.py` · `python eval\run_agent_eval.py [--set holdout2] [--only TEXT]` (uses your LLM key) · `python scripts\check_routes.py` · `python scripts\measure.py` · `.\ship.ps1 "message"` (all checks, then commit and push).

Optional AI agent: set `ALLO_LLM_PROVIDER` (`anthropic` or `openai`), `ALLO_LLM_API_KEY` and `ALLO_LLM_DAILY_BUDGET_USD` in `.env`. Without them everything still works on the rules path.

## Deploy (free)
`render.yaml` is a Render Blueprint: Render dashboard → **New → Blueprint** → this repo → paste `ALLO_PRIM_API_KEY` when asked. Free instances sleep when idle (first request ~30-60 s).

## Phone line (optional, Twilio)
Webhooks `/voice` and `/voice/gather` (signature-checked). Set `ALLO_TWILIO_AUTH_TOKEN` and `ALLO_PUBLIC_BASE_URL`, point the Twilio number's "A call comes in" webhook to `https://<host>/voice`. Not yet tested on a real call.

## Data and privacy
Web questions are stored only when `ALLO_LOG_QUESTIONS=true` (on in the Render blueprint): the question text and its time only, no IP address, no session id, no answer; e-mails and phone numbers are masked; deleted after 30 days; a notice under the search bar says so, and nothing is shown or saved when it is off. The app writes no access log (uvicorn `--no-access-log`). Location for "Near me" never leaves the browser. Phone callers are stored only as HMAC-SHA256; transcripts are deleted after 30 days (background job). Full details: `/privacy` page and [threat model](docs/threat-model.md).

## Known limitations
- Real-time coverage is partial on IDFM's side; scheduled times are labelled as such
- Data can be up to 30 s behind the source (cache protecting the PRIM quota)
- No buses, no fares (the assistant says so)
- Without an LLM key, understanding is rule-based (covers the eval phrasings, not arbitrary sentences)
- AI answers depend on the configured model; the guard prevents invented values, not every possible misunderstanding
- EV: Belib' network only (other operators not covered); reliability thresholds provisional; a status change is dated when the collector saw it (up to 10 min late)
- The AI is not fully consistent from run to run (see the dev-set runs); the guard keeps failures safe, not always useful
- Disruption messages are read in French in English mode (source text is French)
- Web mic uses the browser vendor's speech service; map tiles come from OpenStreetMap (light use only)

## Docs
[Plan](docs/plan.md) · [Decisions](docs/decisions.md) · [Threat model](docs/threat-model.md) · [Eval](eval/README.md)

Data: © Île-de-France Mobilités (PRIM open data) · Vélib' and Belib' data: Ville de Paris open data · Map: © OpenStreetMap contributors.
