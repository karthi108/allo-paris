"""Output validator: every number in spoken text must come from the tool payload.

Used as a guard when any LLM rephrasing is enabled. On failure, callers must fall back
to the deterministic template and log the rejection.
"""

import re

_NUMBER = re.compile(r"\d+")


def numbers_grounded(answer: str, payload_text: str) -> bool:
    allowed = set(_NUMBER.findall(payload_text))
    return all(n in allowed for n in _NUMBER.findall(answer))
