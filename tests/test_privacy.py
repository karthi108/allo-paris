import pytest

from app.core.privacy import caller_id, normalize_e164

KEY = b"test-key"


def test_french_formats_normalize_to_same_id() -> None:
    a = caller_id("06 12 34 56 78", KEY)
    b = caller_id("+33612345678", KEY)
    c = caller_id("0033 6 12 34 56 78", KEY)
    assert a == b == c


def test_id_depends_on_key() -> None:
    assert caller_id("+33612345678", KEY) != caller_id("+33612345678", b"other")


def test_raw_number_not_in_id() -> None:
    assert "612345678" not in caller_id("+33612345678", KEY)


def test_empty_key_rejected() -> None:
    with pytest.raises(ValueError):
        caller_id("+33612345678", b"")


def test_garbage_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_e164("hello")


def test_dotenv_with_bom(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from app.core.config import _load_dotenv

    monkeypatch.delenv("ALLO_BOM_TEST", raising=False)
    env = Path(__file__).parent / "fixtures" / "bom.env"
    env.write_bytes(b"\xef\xbb\xbfALLO_BOM_TEST=ok\n")
    try:
        _load_dotenv(env)
        import os

        assert os.environ["ALLO_BOM_TEST"] == "ok"
    finally:
        env.unlink()
        monkeypatch.delenv("ALLO_BOM_TEST", raising=False)


def test_empty_env_values_mean_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Copying .env.example as is must not crash or switch off Twilio signature checks."""
    from app.core import config

    for name in (
        "ALLO_ENV",
        "ALLO_VERIFY_TWILIO_SIGNATURE",
        "ALLO_DAILY_CALL_CAP",
        "ALLO_LLM_DAILY_BUDGET_USD",
        "ALLO_NAVITIA_URL",
        "ALLO_EV_FLAGS_URL",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(config, "_load_dotenv", lambda path: None)
    config.get_settings.cache_clear()
    try:
        s = config.get_settings()
        assert s.verify_twilio_signature is True
        assert s.daily_call_cap == 200 and s.llm_daily_budget_usd == 1.0
        assert s.navitia_url.startswith("https://prim.") and s.ev_flags_url.endswith("flags.json")
    finally:
        config.get_settings.cache_clear()
