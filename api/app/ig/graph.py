"""Meta Graph API (Business Discovery) adapter.

Business Discovery is a nested field on our own Instagram Business account
node, not a standalone endpoint, and it has no per-media lookup: media urls
exist only inside a listing response.
"""

import json
from urllib.parse import quote

import httpx

from app.config import Settings
from app.ig import graph_map, types as t

_BASE = "https://graph.facebook.com"
_PROFILE_FIELDS = (
    "id,ig_id,username,name,biography,followers_count,media_count,profile_picture_url"
)
_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
    "permalink,timestamp,children{id,media_type,media_url,thumbnail_url}"
)

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


def _httpx_transport(url: str, headers: dict) -> tuple[int, dict, dict]:
    response = httpx.get(url, headers=headers, timeout=30.0)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, {k.lower(): v for k, v in response.headers.items()}, body


def _httpx_fetcher(url: str) -> tuple[int, bytes]:
    response = httpx.get(url, timeout=60.0, follow_redirects=True)
    return response.status_code, response.content


class GraphAdapter:
    """Reads public Business and Creator accounts via Business Discovery."""

    def __init__(self, settings: Settings, transport=None, fetcher=None):
        self._settings = settings
        self._transport = transport or _httpx_transport
        self._fetcher = fetcher or _httpx_fetcher
        self._usage = 0.0

    # ---- transport -----------------------------------------------------
    def _get(self, fields: str) -> dict:
        if not self._settings.graph_token or not self._settings.graph_user_id:
            raise t.IgChallenge(
                "IG_GRAPH_TOKEN and IG_GRAPH_USER_ID must be set to use the Graph adapter."
            )
        # Refuse to spend a call we already know is close to the ceiling.
        if self._usage >= self._settings.graph_usage_limit:
            raise t.IgRateLimited(
                f"app usage at {self._usage:.0f}% of Meta's limit; backing off"
            )

        url = (
            f"{_BASE}/{self._settings.graph_version}/{self._settings.graph_user_id}"
            f"?fields={quote(fields, safe='(),{}.')}"
        )
        # The token goes in a header, never the query string: a url ends up in
        # exception text, the json logs and the activity table.
        headers = {"Authorization": f"Bearer {self._settings.graph_token}"}
        try:
            status, response_headers, body = self._transport(url, headers)
        except t.IgError:
            raise
        except Exception as exc:
            raise t.IgTransient(redact(str(exc), self._settings.graph_token)) from exc

        self._usage = max(self._usage, usage_percent(response_headers))
        if status >= 400 or "error" in body:
            raise classify(status, body, response_headers, self._settings.graph_token)
        return body

    # ---- IgAdapter -----------------------------------------------------
    def login(self) -> None:
        """No interactive login exists; this validates the token instead."""
        self._get("id")

    def fetch_profile(self, username: str) -> t.IgProfile:
        payload = self._get(f"business_discovery.username({username}){{{_PROFILE_FIELDS}}}")
        return graph_map.profile_from_payload(payload)

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        media = f"media.limit({limit})"
        if cursor:
            media += f".after({cursor})"
        payload = self._get(
            f"business_discovery.username({username}){{{media}{{{_MEDIA_FIELDS}}}}}"
        )
        return graph_map.page_from_payload(payload)
