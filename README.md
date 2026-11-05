# Allô Paris

AI voice phone line answering live Paris public transport questions from IDFM open data.

> Unofficial project. Not affiliated with Île-de-France Mobilités or RATP.

**Status:** v1 · phone line + web companion (map, ask box, live boards). See [docs/plan.md](docs/plan.md).

## Design in one line
The parser only works out what the caller wants. Times and status come from live PRIM data and are spoken through fixed templates, so the system cannot invent a departure time. See [D-001](docs/decisions.md).

```
Caller ─► Twilio (speech-to-text, fr-FR/en-GB) ─► POST /voice/gather
            ▲                                          │
            │                                parser (line + stop, fuzzy)
          <Say>                                        │
            │                              PRIM stop-monitoring / general-message
            └──── TwiML ◄── template renderer ◄────────┘
```

## Two ways to use it
- **Phone:** call the number, ask out loud, hear the answer.
- **Web** (`http://localhost:8000/`): map of metro / RER / tram / train stations coloured by line. Click a station → live departures board (auto-refresh 30 s). Ask box with text or browser microphone, FR/EN, optional read-aloud. Feed status in the footer.

Both use the same parser, PRIM client and answer templates, and share one PRIM daily budget.

## What v1 answers
- Next departures: "prochain RER A à Châtelet", "ligne 4 Gare du Nord", "tram T2 La Défense"
- Disruptions: "perturbations sur le RER B"
- Asks back when the line or station is missing or ambiguous
- Says so when real-time data is down or stale, and labels scheduled times

Coverage: metro, RER, tram, Transilien (not bus in v1).

---

## Run it (Windows, PowerShell)

### 1. Install
```powershell
cd "K:\AI\Allo Paris"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```
Expected: all tests pass.

### 2. Configure
```powershell
copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```
Open `.env` and set `ALLO_PRIM_API_KEY` and `ALLO_CALLER_HMAC_KEY` (the value printed above).

### 3. Build the station list (once, ~1 min)
```powershell
python scripts\build_stops.py
```
Expected: `Wrote ~900+ stop areas to ...\data\stops.json`.

### 4. Test with live data, no phone
```powershell
python scripts\ask.py "prochain RER A à Châtelet"
python scripts\ask.py "ligne 4 Gare du Nord"
python scripts\ask.py "perturbations RER B"
python scripts\ask.py --en "line 14 at Châtelet"
```
If this prints departures in minutes, the data layer works.

### 5. Start the server and open the web page
Terminal 1:
```powershell
uvicorn app.api.main:app --port 8000 --proxy-headers
```
Open **http://localhost:8000/** → click a station, or ask "ligne 4 Gare du Nord".
The web page works without Twilio. Steps 6-8 add the phone line.

### 6. Expose it for Twilio
Terminal 2:
```powershell
ngrok http 8000
```
Copy the `https://....ngrok-free.app` URL into `.env` as `ALLO_PUBLIC_BASE_URL`, add `ALLO_TWILIO_AUTH_TOKEN`, then restart uvicorn.
Check: open `http://localhost:8000/health`. It should show `"prim_key": true` and a stop count.

### 7. Connect Twilio
Twilio Console → Phone Numbers → Manage → Active numbers → your number → Voice configuration:
- **A call comes in:** Webhook, `https://YOUR-NGROK-URL/voice`, HTTP POST
- Save

### 8. Call it
Call your Twilio number from your verified phone. Trial accounts play a short Twilio message first, then press any key.
Check results at `http://localhost:8000/stats` (calls, intents, latency).

---

## Limits and privacy
- PRIM daily budget shared by phone + web (default 900/day), web rate limit per IP (20/min)
- Daily global call cap, per-caller daily limit, max call duration (see `.env`)
- Caller numbers stored only as HMAC-SHA256; no audio stored by this app
- Transcripts deleted after 30 days
- Speech recognition and voice are done by Twilio (processor); check its retention settings

## Known limitations (v1)
- Speech recognition is Twilio's, not streaming: expect ~2-3 s per answer
- Disruption messages are read in French even in English mode (PRIM text is French)
- No buses, no Vélib, no A→B routing yet
- Web microphone uses the browser's speech service (Chrome/Edge), not ours
- Scheduled times are only what PRIM returns; no GTFS timetable fallback yet

## Docs
- [Plan](docs/plan.md) · [Decisions](docs/decisions.md) · [Threat model](docs/threat-model.md)

## Results
_Filled only with measured values._
