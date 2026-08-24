"""Meta Graph API (Business Discovery) adapter.

Business Discovery is a nested field on our own Instagram Business account
node, not a standalone endpoint, and it has no per-media lookup: media urls
exist only inside a listing response.
"""

import json
from pathlib import Path
from urllib.parse import quote

import httpx

from app import paths
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

_STALE_STATUSES = {403, 404, 410}

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


class _Stale(Exception):
    """A cached CDN url has expired. Internal to this module."""


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
        self._usage_peak = 0.0

    @property
    def usage(self) -> float:
        """Meta's latest reported percentage of the hourly quota."""
        return self._usage

    @property
    def usage_peak(self) -> float:
        """Highest reading seen this process. What the backoff guard trusts."""
        return self._usage_peak

    # ---- transport -----------------------------------------------------
    def _get(self, fields: str) -> dict:
        if not self._settings.graph_token or not self._settings.graph_user_id:
            raise t.IgChallenge(
                "IG_GRAPH_TOKEN and IG_GRAPH_USER_ID must be set to use the Graph adapter."
            )
        # Refuse to spend a call we already know is close to the ceiling.
        if self._usage_peak >= self._settings.graph_usage_limit:
            raise t.IgRateLimited(
                f"app usage at {self._usage_peak:.0f}% of Meta's limit; backing off"
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

        # Latest for the readout, peak for the guard: the hourly window
        # resets, so a figure that only ever climbs stops being true.
        self._usage = usage_percent(response_headers)
        self._usage_peak = max(self._usage_peak, self._usage)
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

    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: t.MediaHint | None = None
    ) -> list[t.SavedFile]:
        sources = tuple(hint.sources) if hint else ()
        if not sources:
            sources = self._refresh(shortcode, hint)
        try:
            return self._download_all(sources, dest_dir)
        except _Stale:
            # Meta's CDN urls expire. Shallow indexing makes a bounded
            # re-listing cheap, so this is recoverable rather than fatal.
            return self._download_all(self._refresh(shortcode, hint), dest_dir)

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        try:
            return self._download(t.MediaSource(0, url, "image/jpeg", False), dest)
        except _Stale as exc:
            raise t.IgTransient(f"could not download {dest.name}") from exc

    # ---- internals -----------------------------------------------------
    def _refresh(self, shortcode: str, hint: t.MediaHint | None) -> tuple[t.MediaSource, ...]:
        if hint is None or not hint.username:
            raise t.IgNotFound(
                f"{shortcode} has no owning profile recorded; re-sync it before opening"
            )
        cursor: str | None = None
        for _ in range(max(1, self._settings.graph_refresh_pages)):
            page = self.fetch_page(hint.username, cursor, self._settings.page_size)
            for post in page.posts:
                if post.shortcode == shortcode:
                    if not post.sources:
                        # Found it, and Meta published no file for it.
                        # Business Discovery omits media_url for every reel,
                        # so the video is not merely stale -- it was never
                        # offered, and no retry will produce one.
                        raise t.IgNotFound(
                            f"Meta publishes no downloadable file for {shortcode}: "
                            "Business Discovery returns only a thumbnail for a "
                            "reel, never the video itself"
                        )
                    return post.sources
            cursor = page.next_cursor
            if cursor is None:
                break
        raise t.IgNotFound(
            f"{shortcode} is too far back to refresh; re-sync {hint.username} to open it"
        )

    def _download_all(
        self, sources: tuple[t.MediaSource, ...], dest_dir: Path
    ) -> list[t.SavedFile]:
        saved = []
        for source in sources:
            ext = "mp4" if source.is_video else "jpg"
            dest = dest_dir / paths.full_filename(source.child_idx, ext)
            saved.append(self._download(source, dest))
        return saved

    def _download(self, source: t.MediaSource, dest: Path) -> t.SavedFile:
        try:
            status, payload = self._fetcher(source.url)
        except Exception as exc:
            raise t.IgTransient(redact(str(exc), self._settings.graph_token)) from exc
        if status in _STALE_STATUSES:
            raise _Stale(source.url)
        if status >= 400 or not payload:
            raise t.IgTransient(f"CDN returned {status}")
        size = paths.atomic_write(dest, lambda fh: fh.write(payload))
        return t.SavedFile(
            child_idx=source.child_idx,
            path=dest,
            mime=source.mime,
            bytes=size,
            width=None,
            height=None,
        )
