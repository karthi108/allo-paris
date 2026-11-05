"""Caller pseudonymisation. See docs/decisions.md D-002.

A plain hash of a phone number is reversible by brute force (small number space),
so we use HMAC-SHA256 with a secret key. The result is pseudonymised personal data.
"""

import hashlib
import hmac
import re

_NON_DIGITS = re.compile(r"[^\d+]")


def normalize_e164(number: str) -> str:
    """Normalize a French or international number to E.164 (+33...)."""
    cleaned = _NON_DIGITS.sub("", number)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 10:
        cleaned = "+33" + cleaned[1:]
    if not cleaned.startswith("+") or len(cleaned) < 8:
        raise ValueError("unrecognised phone number format")
    return cleaned


def caller_id(number: str, key: bytes) -> str:
    """Return a stable pseudonymous caller ID. The raw number must never be logged."""
    if not key:
        raise ValueError("HMAC key must not be empty")
    return hmac.new(key, normalize_e164(number).encode(), hashlib.sha256).hexdigest()
