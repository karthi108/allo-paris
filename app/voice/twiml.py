"""TwiML builders and Twilio request signature validation (stdlib only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
from xml.sax.saxutils import escape, quoteattr

LANG_CODES = {"fr": "fr-FR", "en": "en-GB"}

# Speech hints improve recognition of station names over 8 kHz phone audio
HINTS = (
    "RER A, RER B, RER C, RER D, RER E, ligne 1, ligne 4, ligne 13, ligne 14, Châtelet, "
    "Châtelet Les Halles, Gare du Nord, Gare de Lyon, Saint-Lazare, Montparnasse, "
    "La Défense, Nation, République, Bastille, Château Rouge, Château d'Eau, "
    "Saint-Michel Notre-Dame, Charles de Gaulle Étoile, perturbations, trafic"
)


def _say(text: str, lang: str, voice: str) -> str:
    voice_attr = f" voice={quoteattr(voice)}" if voice else ""
    return f"<Say language={quoteattr(LANG_CODES[lang])}{voice_attr}>{escape(text)}</Say>"


def gather(text: str, lang: str, action: str, voice: str = "") -> str:
    """Speak, then listen for speech and POST the result to `action`."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f'<Gather input="speech" language={quoteattr(LANG_CODES[lang])} '
        f'speechTimeout="auto" actionOnEmptyResult="true" method="POST" '
        f"action={quoteattr(action)} hints={quoteattr(HINTS)}>"
        f"{_say(text, lang, voice)}</Gather></Response>"
    )


def hangup(text: str, lang: str, voice: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f"{_say(text, lang, voice)}<Hangup/></Response>"
    )


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio scheme: base64(HMAC-SHA1(token, url + concat(sorted key+value)))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)
