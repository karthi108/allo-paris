"""Settings from environment variables (and an optional .env file). Never hardcode secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, # comments. Real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    env: str
    public_base_url: str
    prim_api_key: str
    twilio_auth_token: str
    verify_twilio_signature: bool
    caller_hmac_key: bytes
    daily_call_cap: int
    per_caller_calls_per_day: int
    max_call_seconds: int
    transcript_retention_days: int
    realtime_stale_after_seconds: int
    cache_ttl_seconds: int
    prim_daily_budget: int
    web_requests_per_minute: int
    db_path: Path
    stops_path: Path
    tts_voice_fr: str
    tts_voice_en: str
    public_phone: str


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get("ALLO_ENV", "dev")
    hmac_key = os.environ.get("ALLO_CALLER_HMAC_KEY", "")
    if env != "dev" and len(hmac_key) < 32:
        raise RuntimeError("ALLO_CALLER_HMAC_KEY must be set (32+ chars) outside dev")
    return Settings(
        env=env,
        public_base_url=os.environ.get("ALLO_PUBLIC_BASE_URL", "").rstrip("/"),
        prim_api_key=os.environ.get("ALLO_PRIM_API_KEY", ""),
        twilio_auth_token=os.environ.get("ALLO_TWILIO_AUTH_TOKEN", ""),
        verify_twilio_signature=os.environ.get("ALLO_VERIFY_TWILIO_SIGNATURE", "true") == "true",
        caller_hmac_key=(hmac_key or "dev-only-change-me").encode(),
        daily_call_cap=_int("ALLO_DAILY_CALL_CAP", 200),
        per_caller_calls_per_day=_int("ALLO_PER_CALLER_CALLS_PER_DAY", 10),
        max_call_seconds=_int("ALLO_MAX_CALL_SECONDS", 180),
        transcript_retention_days=_int("ALLO_TRANSCRIPT_RETENTION_DAYS", 30),
        realtime_stale_after_seconds=_int("ALLO_REALTIME_STALE_AFTER_SECONDS", 120),
        cache_ttl_seconds=_int("ALLO_CACHE_TTL_SECONDS", 30),
        prim_daily_budget=_int("ALLO_PRIM_DAILY_BUDGET", 900),
        web_requests_per_minute=_int("ALLO_WEB_REQUESTS_PER_MINUTE", 20),
        db_path=Path(os.environ.get("ALLO_DB_PATH", ROOT / "data" / "allo.db")),
        stops_path=Path(os.environ.get("ALLO_STOPS_PATH", ROOT / "data" / "stops.json")),
        tts_voice_fr=os.environ.get("ALLO_TTS_VOICE_FR", ""),
        tts_voice_en=os.environ.get("ALLO_TTS_VOICE_EN", ""),
        public_phone=os.environ.get("ALLO_PUBLIC_PHONE", ""),
    )
