"""Pure mapping from Meta Business Discovery JSON onto our own types.

Deliberately free of network, settings and side effects: this is the code
that breaks when Meta reshapes a response, and purity is what lets it be
tested against recorded fixtures.
"""

import re

from app.ig import types as t

_PERMALINK = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def shortcode_from_permalink(permalink: str) -> str:
    match = _PERMALINK.search(permalink or "")
    if match is None:
        raise ValueError(f"no shortcode in permalink: {permalink!r}")
    return match.group(1)


def profile_from_payload(payload: dict) -> t.IgProfile:
    bd = payload["business_discovery"]
    return t.IgProfile(
        username=bd["username"],
        user_id=str(bd.get("id") or ""),
        full_name=bd.get("name") or "",
        biography=bd.get("biography") or "",
        # Business Discovery only ever returns public Business/Creator
        # accounts. A private one is an error, not a private-looking result.
        is_private=False,
        post_count=int(bd.get("media_count") or 0),
        avatar_url=bd.get("profile_picture_url") or "",
    )
