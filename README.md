# Allô Paris

Live Paris transport answers, on the web and by phone, from official Île-de-France Mobilités real-time open data.

> Independent project using official IDFM real-time open data (PRIM). Not affiliated with or endorsed by Île-de-France Mobilités or RATP.

**Status:** v1 · web app working on live data · phone line built, not yet tested on a real call · see [plan](docs/plan.md).

## What it does
- **Next departures** for metro, RER, tram and Transilien: "prochain RER A à Châtelet", "la 13 à Saint-Lazare", "line four at chateau rouge"
- **Disruptions:** "perturbations RER B", "any delays on line 4"
- **Vélib' nearby:** "Vélib à Bastille", "any bikes near the Eiffel Tower" (bikes, e-bikes, free docks)
- **Landmarks:** Eiffel Tower, Louvre, Sacré-Cœur, airports, Disneyland… mapped to the nearest station, typos tolerated
- **Asks back** when the line or station is missing or ambiguous; **says so** for things it doesn't do (journeys, future timetables, buses)
- **Web app:** full-screen map of 979 stations, search with autocomplete, boards grouped by direction (30 s refresh), disruption banner, Vélib nearby, Near me, favourites, mic input and read-aloud, FR/EN, light/dark, mobile bottom sheet

## Design in one line
The parser only works out *what* is asked. Every time, status and bike count comes from a live data source and is spoken through fixed templates, so the system **cannot invent a departure time**. See [D-001](docs/decisions.md).

```
 Web (text / mic) ─┐                                   ┌─► IDFM PRIM  next departures (cache 30 s)
                   ├─► parser ─► dialog ─► data layer ─┼─► IDFM PRIM  traffic messages (cache 5 min)
 Phone (Twilio) ───┘   rules +    clarify   quotas,    └─► Paris open data  Vélib' (cache 60 s)
                       fuzzy      or answer  caching
                       matching   (templates only)
```

## Results (measured)
| Metric | Value | How |
|---|---|---|
| Intent accuracy | **61/61 (100%)** | `python eval/run_eval.py`, synthetic FR/EN question set on the full IDFM station list |
| Line / station accuracy | **100% / 100%** | same eval |
| Invented numbers in answers | **0** | eval checks every number against data source, templates and names |
| Tests | **87 passing** | `pytest`, run in CI with ruff, mypy strict, gitleaks |
| Answer latency p50 / p95 | _pending: run `python scripts/measure.py`_ | live PRIM, cache off |

The eval questions were written by the author (labelled `synthetic`); real user questions will be added from a beta. Results show the parser handles the covered phrasings, not every possible sentence.

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
Other commands: `python scripts\ask.py "ligne 4 Gare du Nord"` (live answer in the terminal) · `python eval\run_eval.py` · `python scripts\measure.py` · `.\ship.ps1 "message"` (all checks, then commit and push).

## Deploy (free)
`render.yaml` is a Render Blueprint: Render dashboard → **New → Blueprint** → this repo → paste `ALLO_PRIM_API_KEY` when asked. Free instances sleep when idle (first request ~30-60 s).

## Phone line (optional, Twilio)
Webhooks `/voice` and `/voice/gather` (signature-checked). Set `ALLO_TWILIO_AUTH_TOKEN` and `ALLO_PUBLIC_BASE_URL`, point the Twilio number's "A call comes in" webhook to `https://<host>/voice`. Not yet tested on a real call.

## Data and privacy
No web questions are stored. Location for "Near me" never leaves the browser. Phone callers are stored only as HMAC-SHA256; transcripts are deleted after 30 days (background job). Full details: `/privacy` page and [threat model](docs/threat-model.md).

## Known limitations
- Real-time coverage is partial on IDFM's side; scheduled times are labelled as such
- Data can be up to 30 s behind the source (cache protecting the PRIM quota)
- No buses, no journey planning, no future timetables (the assistant says so)
- Rule-based understanding: covers the phrasings in the eval set, not arbitrary sentences
- Disruption messages are read in French in English mode (source text is French)
- Web mic uses the browser vendor's speech service; map tiles come from OpenStreetMap (light use only)

## Docs
[Plan](docs/plan.md) · [Decisions](docs/decisions.md) · [Threat model](docs/threat-model.md) · [Eval](eval/README.md)

Data: © Île-de-France Mobilités (PRIM open data) · Vélib' data: Ville de Paris open data · Map: © OpenStreetMap contributors.
