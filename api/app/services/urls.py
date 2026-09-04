"""Turns a pasted Instagram link into the shortcode the rest of the app keys on.

Accepts the three shapes Instagram itself hands out -- /p/, /reel/ and /tv/ --
with or without scheme, www, a trailing slash, a query string, or the owner's
username in front (share links sometimes carry it). Anything else is None
rather than a guess: a wrong shortcode would queue work against a post that
does not exist.
"""

import re

_SHORTCODE = re.compile(
    r"^(?:https?://)?(?:www\.)?instagram\.com"
    r"(?:/[A-Za-z0-9_.]+)?"  # optional owner segment in share links
    r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?(?:[?#].*)?$"
)


def parse_shortcode(text: str) -> str | None:
    match = _SHORTCODE.match(text.strip())
    return match.group(1) if match else None
