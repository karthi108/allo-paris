"""FastAPI entrypoint: Twilio webhooks, web companion (map + ask), health and stats.

Run:  uvicorn app.api.main:app --port 8000 --proxy-headers
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from app.agent.agent import Agent
from app.agent.dialog import Dialog
from app.agent.llm import make_client
from app.agent.tools import Toolbox
from app.api.web import RateLimiter, WebApi
from app.core.config import get_settings
from app.core.metrics import Metrics
from app.core.store import Store
from app.data.prim import PrimClient
from app.data.routes import RouteClient
from app.data.stops import StopIndex
from app.data.velib import VelibClient
from app.ev.live import ChargerClient
from app.voice import twiml
from app.voice.calls import CallConfig, CallHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
if not settings.stops_path.exists():
    raise RuntimeError(f"{settings.stops_path} missing. Run: python scripts/build_stops.py")

index = StopIndex.load(settings.stops_path)
prim = PrimClient(
    settings.prim_api_key,
    cache_ttl=settings.cache_ttl_seconds,
    daily_budget=settings.prim_daily_budget,
)
velib = VelibClient()
chargers = ChargerClient(flags_url=settings.ev_flags_url)
routes = RouteClient(
    settings.prim_api_key, url=settings.navitia_url, daily_budget=settings.route_daily_budget
)
llm = make_client(
    settings.llm_provider,
    settings.llm_api_key,
    model=settings.llm_model,
    daily_usd=settings.llm_daily_budget_usd,
    price_in=settings.llm_price_in,
    price_out=settings.llm_price_out,
)
agent = Agent(llm, lambda: Toolbox(index, prim, velib, routes, chargers=chargers)) if llm else None
metrics = Metrics()
dialog = Dialog(
    index,
    prim,
    stale_after=settings.realtime_stale_after_seconds,
    bikes=velib,
    agent=agent,
    metrics=metrics,
    chargers=chargers,
)
store = Store(settings.db_path, settings.transcript_retention_days)
calls = CallHandler(
    dialog,
    store,
    CallConfig(
        hmac_key=settings.caller_hmac_key,
        daily_call_cap=settings.daily_call_cap,
        per_caller_calls_per_day=settings.per_caller_calls_per_day,
        max_call_seconds=settings.max_call_seconds,
        voice_fr=settings.tts_voice_fr,
        voice_en=settings.tts_voice_en,
    ),
)

web = WebApi(index, dialog, stale_after=settings.realtime_stale_after_seconds)
# Questions to the assistant can cost LLM money: tight limit. Data reads (boards, Vélib',
# chargers, status) are cheap and a map page makes several per click: looser limit, still
# bounded by the daily PRIM budget. One shared 20/min limit made the page fail on 2-3 clicks.
limiter = RateLimiter(per_minute=settings.web_requests_per_minute)
data_limiter = RateLimiter(per_minute=max(settings.web_requests_per_minute * 6, 60))
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "img-src 'self' data: https://*.tile.openstreetmap.org https://cdnjs.cloudflare.com; "
    "connect-src 'self'; frame-ancestors 'none'"
)

app = FastAPI(title="Allô Paris", version="0.3.0", docs_url=None, redoc_url=None)
log = logging.getLogger("allo.main")


def _purge_loop() -> None:
    """Delete transcripts older than the retention period every 6 hours, even with no calls."""
    while True:
        try:
            removed = store.purge()
            if removed:
                log.info("retention purge removed %s rows", removed)
        except Exception:  # never let the cleanup thread die silently
            log.exception("retention purge failed")
        time.sleep(6 * 3600)


threading.Thread(target=_purge_loop, name="retention-purge", daemon=True).start()


async def _twilio_params(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    params = dict(parse_qsl(body, keep_blank_values=True))
    if settings.verify_twilio_signature:
        # Behind ngrok/a proxy, request.url is the internal URL; Twilio signs the public one.
        url = f"{settings.public_base_url}{request.url.path}"
        sig = request.headers.get("X-Twilio-Signature", "")
        if not twiml.valid_signature(settings.twilio_auth_token, url, params, sig):
            raise HTTPException(status_code=403, detail="invalid signature")
    return params


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


@app.get("/health")
def health() -> JSONResponse:
    """For uptime monitors: 503 when the PRIM key is missing or the last PRIM call failed."""
    p = prim.status()
    failing = not p["configured"] or (
        p["last_error_at"] is not None
        and (p["last_ok_at"] is None or str(p["last_error_at"]) > str(p["last_ok_at"]))
    )
    body = {
        "status": "degraded" if failing else "ok",
        "stops": len(index.areas),
        "prim": p,
        "velib": velib.status(),
        "belib": chargers.status(),
    }
    return JSONResponse(body, status_code=503 if failing else 200)


def _ai_status() -> dict[str, Any]:
    if llm is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "provider": llm.provider,
        "model": llm.model,
        "calls_today": llm.budget.calls_today,
        "spent_usd_today": round(llm.budget.spent_usd, 4),
        "daily_budget_usd": llm.budget.daily_usd,
    }


@app.get("/api/metrics")
def api_metrics() -> dict[str, Any]:
    """Public, aggregate only: no question text, no IPs."""
    return {
        "service": metrics.snapshot(),
        "ai": _ai_status(),
        "prim": prim.status(),
        "routes": routes.status(),
        "velib": velib.status(),
        "belib": chargers.status(),
    }


@app.get("/metrics")
def metrics_page() -> FileResponse:
    return FileResponse(
        WEB_DIR / "metrics.html",
        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-cache"},
    )


@app.get("/metrics.js")
def metrics_js() -> FileResponse:
    return FileResponse(
        WEB_DIR / "metrics.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness for the host (Render): the process is up. Feed health is /health."""
    return {"status": "alive"}


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(
        WEB_DIR / "privacy.html",
        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-cache"},
    )


@app.get("/stats")
def stats() -> dict[str, object]:
    return {**store.stats(), "prim_calls_made": prim.calls_made}


@app.post("/voice")
async def voice(request: Request) -> Response:
    return _xml(calls.incoming(await _twilio_params(request)))


@app.post("/voice/gather")
async def voice_gather(request: Request) -> Response:
    return _xml(calls.speech(await _twilio_params(request)))


def _limit(request: Request, which: RateLimiter | None = None) -> None:
    ip = request.client.host if request.client else "unknown"
    if not (which or data_limiter).allow(ip):
        raise HTTPException(status_code=429, detail="too many requests, slow down")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={
            "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(
        WEB_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},  # always revalidate so updates show up
    )


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> FileResponse:
    return favicon()


@app.get("/api/chargers")
def api_chargers(request: Request, stop: str) -> dict[str, Any]:
    _limit(request)
    return web.chargers(stop)


@app.get("/api/chargers/near")
def api_chargers_near(request: Request, lat: float, lon: float) -> dict[str, Any]:
    _limit(request)
    if not (48.6 <= lat <= 49.1 and 2.0 <= lon <= 2.7):  # Île-de-France box
        raise HTTPException(status_code=400, detail="outside the covered area")
    return web.chargers_near(lat, lon)


@app.get("/api/chargers/map")
def api_chargers_map(request: Request) -> dict[str, Any]:
    _limit(request)
    return web.chargers_map()


@app.get("/api/velib")
def api_velib(request: Request, stop: str) -> dict[str, Any]:
    _limit(request)
    return web.velib(stop)


@app.get("/api/traffic")
def api_traffic(request: Request, line: str) -> dict[str, Any]:
    _limit(request)
    return web.traffic(line)


@app.get("/api/stops")
def api_stops() -> list[dict[str, Any]]:
    return web.stops()


@app.get("/api/departures")
def api_departures(request: Request, stop: str, line: str, lang: str = "fr") -> dict[str, Any]:
    _limit(request)
    return web.departures(stop, line, lang)


@app.post("/api/ask")
async def api_ask(request: Request) -> dict[str, Any]:
    _limit(request, limiter)
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    return web.ask(
        str(body.get("q", "")), str(body.get("session", ""))[:64], str(body.get("lang", "fr"))
    )


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return {
        "prim": prim.status(),
        "velib": velib.status(),
        "belib": chargers.status(),
        "routes": routes.status(),
        "ai": _ai_status(),
        "stops": len(index.areas),
        # Only advertise the number when the phone line can actually answer
        "phone": settings.public_phone
        if settings.twilio_auth_token and settings.public_base_url
        else "",
    }
