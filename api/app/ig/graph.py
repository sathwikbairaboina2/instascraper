"""Meta Graph API (Business Discovery) adapter.

Business Discovery is a nested field on our own Instagram Business account
node, not a standalone endpoint, and it has no per-media lookup: media urls
exist only inside a listing response.
"""

import json

from app.ig import types as t

_CHALLENGE_CODES = {102, 190}
_RATE_LIMIT_CODES = {4, 17, 32, 613}
_TRANSIENT_CODES = {1, 2}

# Meta has no dedicated code for "this target is not a Business account", so
# the message is the only signal. Confirmed against a real response by the
# live canary; if that test reports something else, correct these lists
# rather than loosening the assertion.
_NOT_BUSINESS_HINTS = ("not an instagram business", "not a business", "business or creator")
_NOT_FOUND_HINTS = ("invalid user id", "does not exist", "cannot be found")


def redact(text: str, token: str) -> str:
    """Never let a token reach a log line, the activity table, or an error."""
    if token and token in text:
        return text.replace(token, "[redacted]")
    return text


def usage_percent(headers: dict) -> float:
    """Highest of Meta's three app-usage counters, as a percentage.

    Meta throttles on whichever counter saturates first, so the maximum is
    the only number worth acting on.
    """
    raw = (headers or {}).get("x-app-usage")
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return 0.0
    values = [data.get(k, 0) for k in ("call_count", "total_cputime", "total_time")]
    return float(max(values or [0]))


def _retry_after(headers: dict) -> float | None:
    """Meta sends no Retry-After, but throttling replies estimate the wait."""
    raw = (headers or {}).get("x-business-use-case-usage")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    for entries in data.values():
        for entry in entries or []:
            minutes = entry.get("estimated_time_to_regain_access")
            if minutes:
                return float(minutes) * 60.0
    return None


def classify(
    status: int, payload: dict, headers: dict | None = None, token: str = ""
) -> t.IgError:
    """Map a Meta failure onto the five cases the worker knows how to handle."""
    error = (payload or {}).get("error") or {}
    code = error.get("code")
    message = redact(error.get("message") or f"HTTP {status}", token)
    lowered = message.lower()

    if code in _CHALLENGE_CODES or (isinstance(code, int) and 200 <= code <= 299):
        return t.IgChallenge(message)
    if code in _RATE_LIMIT_CODES:
        return t.IgRateLimited(message, retry_after=_retry_after(headers or {}))
    if any(hint in lowered for hint in _NOT_BUSINESS_HINTS):
        return t.IgPrivate(message)
    if any(hint in lowered for hint in _NOT_FOUND_HINTS):
        return t.IgNotFound(message)
    if code in _TRANSIENT_CODES or status >= 500:
        return t.IgTransient(message)
    return t.IgTransient(message)
