# Allô Paris

A hybrid AI transport assistant for Paris: deterministic rules for the common questions, an LLM agent with tool calling for everything else, and a grounding guard that blocks any number or line the data sources did not return. Web and phone, on official Île-de-France Mobilités real-time open data.

> Independent project using official IDFM real-time open data (PRIM). Not affiliated with or endorsed by Île-de-France Mobilités or RATP.

**Status:** v1 · web app working on live data · AI agent and routes built, live check pending · phone line built, not yet tested on a real call · see [plan](docs/plan.md).

## What it does
- **Next departures** for metro, RER, tram and Transilien: "prochain RER A à Châtelet", "la 13 à Saint-Lazare", "line four at chateau rouge"
- **Disruptions:** "perturbations RER B", "any delays on line 4"
- **Vélib' nearby:** "Vélib à Bastille", "any bikes near the Eiffel Tower" (bikes, e-bikes, free docks)
- **Landmarks:** Eiffel Tower, Louvre, Sacré-Cœur, airports, Disneyland… mapped to the nearest station, typos tolerated
- **Routes (AI agent + IDFM's official journey planner):** "fastest way from Gare du Nord to the Eiffel Tower", "demain à 8h de Nation à La Défense"; checks live disruptions on every line of the journey and recommends the alternative when one is disrupted
- **Asks back** when the origin, line or station is missing or ambiguous; **declines** what it doesn't cover (fares, buses) and refuses prompt-injection attempts
- **Web app:** full-screen map of 979 stations, search with autocomplete, boards grouped by direction (30 s refresh), disruption banner, Vélib nearby, Near me, favourites, mic input and read-aloud, FR/EN, light/dark, mobile bottom sheet

## How it answers
```
question ─► injection filter ─► rules parser ──── confident? ──► template answer        (free, ~76 ms)
                                     │ no
                                     ▼
                         LLM agent (OpenAI or Anthropic, tool calling)
                           find_station · next_departures · line_status
                           velib_nearby · plan_route (IDFM planner + live disruptions)
                                     │ draft answer
                                     ▼
                         grounding guard: every number and line must be in tool results
                           pass ─► answer      fail ─► 1 retry ─► fail ─► safe template
```
- **Rules first:** most questions never reach the LLM: zero cost, deterministic, fast.
- **The LLM only understands and phrases.** Times, lines and routes come from tools over live data; the guard rejects anything else. See [D-001](docs/decisions.md), [D-018](docs/decisions.md).
- **Graceful degradation:** no key, budget cap reached or provider down → the rules path keeps working.
- **Public live metrics** at `/metrics`: share of questions needing the AI, latency per path, guard corrections and blocks, AI cost today. Aggregates only, no question text.

## Results (measured)
| Metric | Value | How |
|---|---|---|
| Intent accuracy | **61/61 (100%)** | `python eval/run_eval.py`, synthetic FR/EN question set on the full IDFM station list |
| Line / station accuracy | **100% / 100%** | same eval |
| Invented numbers in answers | **0** | eval checks every number against data source, templates and names |
| Tests | **87 passing** | `pytest`, run in CI with ruff, mypy strict, gitleaks |
| Answer latency p50 / p95 | **76 ms / 311 ms** (max 321 ms) | `python scripts/measure.py`: 20 questions on live PRIM + Vélib, cache off, server-side from a home connection, 2026-11-07 (excludes browser/phone network) |
| Live answers | **20/20, 0 feed errors** | same run, 18 PRIM calls |

**Rules vs hybrid AI** (`python eval/run_agent_eval.py`, 22 route, messy and adversarial questions, real LLM on fixed data with a scripted RER B disruption):

| Mode | Success | Routes | Messy | Adversarial | p50 latency | Cost / question |
|---|---|---|---|---|---|---|
| Rules only | 7/22 (32%) | 0/11 | 2/5 | 5/6 | ≈0 ms | 0 |
| Hybrid (rules + AI) | _run pending_ | | | | | |

The eval questions were written by the author (labelled `synthetic`); real user questions will be added from a beta.

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
Other commands: `python scripts\ask.py "ligne 4 Gare du Nord"` (live answer in the terminal) · `python eval\run_eval.py` · `python eval\run_agent_eval.py` (uses your LLM key) · `python scripts\check_routes.py` · `python scripts\measure.py` · `.\ship.ps1 "message"` (all checks, then commit and push).

Optional AI agent: set `ALLO_LLM_PROVIDER` (`anthropic` or `openai`), `ALLO_LLM_API_KEY` and `ALLO_LLM_DAILY_BUDGET_USD` in `.env`. Without them everything still works on the rules path.

## Deploy (free)
`render.yaml` is a Render Blueprint: Render dashboard → **New → Blueprint** → this repo → paste `ALLO_PRIM_API_KEY` when asked. Free instances sleep when idle (first request ~30-60 s).

## Phone line (optional, Twilio)
Webhooks `/voice` and `/voice/gather` (signature-checked). Set `ALLO_TWILIO_AUTH_TOKEN` and `ALLO_PUBLIC_BASE_URL`, point the Twilio number's "A call comes in" webhook to `https://<host>/voice`. Not yet tested on a real call.

## Data and privacy
No web questions are stored. Location for "Near me" never leaves the browser. Phone callers are stored only as HMAC-SHA256; transcripts are deleted after 30 days (background job). Full details: `/privacy` page and [threat model](docs/threat-model.md).

## Known limitations
- Real-time coverage is partial on IDFM's side; scheduled times are labelled as such
- Data can be up to 30 s behind the source (cache protecting the PRIM quota)
- No buses, no fares (the assistant says so)
- Without an LLM key, understanding is rule-based (covers the eval phrasings, not arbitrary sentences)
- AI answers depend on the configured model; the guard prevents invented values, not every possible misunderstanding
- Disruption messages are read in French in English mode (source text is French)
- Web mic uses the browser vendor's speech service; map tiles come from OpenStreetMap (light use only)

## Docs
[Plan](docs/plan.md) · [Decisions](docs/decisions.md) · [Threat model](docs/threat-model.md) · [Eval](eval/README.md)

Data: © Île-de-France Mobilités (PRIM open data) · Vélib' data: Ville de Paris open data · Map: © OpenStreetMap contributors.
