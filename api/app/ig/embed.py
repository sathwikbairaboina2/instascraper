"""Reads the owner's handle off a post's public embed page.

Business Discovery is the app's picture source, but it is keyed by username
and cannot look up an arbitrary shortcode. A pasted link names a post and
nobody else, so something has to say who owns it before the Graph API can be
asked anything at all. For a video yt-dlp answers that as a side effect of
downloading; for an image post it refuses outright, and this is the gap.

The embed page is what Instagram serves to any site that embeds a post, so
reading it needs no session and reveals nothing a visitor could not see.
Only the handle is taken from it: the pictures still come from the Graph API,
which serves full resolution and every carousel child, neither of which the
embed page has. Like the reel downloader, this counts against the scraping
cap -- it is a request to instagram.com, and the cap measures those.
"""

import html
import re
from typing import Callable

import httpx

from app.config import Settings
from app.ig import types as t
from app.services.urls import parse_shortcode
from app.worker.pacer import Pacer

Fetcher = Callable[[str, float], tuple[int, str]]

_EMBED = "https://www.instagram.com/p/{shortcode}/embed/captioned/"

# The handle appears twice on the page: in the app deep link beside the
# "View profile" button, and in that button's href. Either will do, and
# having both means a markup change has to break both to matter.
_OWNER = (
    re.compile(r"data-ios-link=\"user\?username=([A-Za-z0-9_.]+)"),
    re.compile(r"class=\"ViewProfileButton\" href=\"https://www\.instagram\.com/([A-Za-z0-9_.]+)/"),
)


def _httpx_fetcher(url: str, timeout: float) -> tuple[int, str]:
    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        # Instagram serves the embed page to browsers; the default httpx
        # agent gets a stub with no handle on it. This is the one header
        # that makes the page render, not a disguise.
        headers={"User-Agent": "Mozilla/5.0"},
    )
    return response.status_code, response.text


class EmbedLookup:
    def __init__(
        self,
        settings: Settings,
        fetcher: Fetcher | None = None,
        pacer: Pacer | None = None,
        spend: Callable[[], None] | None = None,
    ):
        self._settings = settings
        self._fetcher = fetcher or _httpx_fetcher
        self._pacer = pacer or Pacer(min_interval=settings.reel_min_interval)
        # Injected for the same reason the downloader's is: adapters have no
        # database access, and the ledger lives in the database.
        self._spend = spend or (lambda: None)

    def owner(self, url: str) -> str:
        shortcode = parse_shortcode(url)
        if shortcode is None:
            raise t.IgNotFound(f"not an Instagram post url: {url}")

        # Spent before the request, not after it: a page that comes back
        # empty still sent the request the cap exists to limit.
        self._spend()
        self._pacer.wait()

        try:
            status, body = self._fetcher(
                _EMBED.format(shortcode=shortcode), self._settings.reel_timeout
            )
        except Exception as exc:
            raise t.IgTransient(f"could not reach the embed page for {shortcode}") from exc
        if status >= 400:
            raise t.IgTransient(f"the embed page for {shortcode} returned {status}")

        for pattern in _OWNER:
            match = pattern.search(body or "")
            if match:
                return html.unescape(match.group(1))
        # Deleted, private and age-gated posts all render a page with no
        # handle on it. None of them become fetchable by asking again.
        raise t.IgNotFound(f"{shortcode} has no public owner to look up")
