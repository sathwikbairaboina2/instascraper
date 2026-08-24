"""Pure mapping from Meta Business Discovery JSON onto our own types.

Deliberately free of network, settings and side effects: this is the code
that breaks when Meta reshapes a response, and purity is what lets it be
tested against recorded fixtures.
"""

import re
from datetime import datetime

from app.ig import types as t

_PERMALINK = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")
_KIND = {"IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}


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
        followers_count=int(bd.get("followers_count") or 0),
        avatar_url=bd.get("profile_picture_url") or "",
    )


def _mime(media_type: str) -> str:
    # Meta does not return a content type in a listing, so it is derived.
    return "video/mp4" if media_type == "VIDEO" else "image/jpeg"


def _children(node: dict) -> list[dict]:
    return (node.get("children") or {}).get("data") or []


def _timestamp(raw: str) -> str:
    """Meta sends `+0000`; the rest of the app stores `+00:00`."""
    return datetime.fromisoformat(raw).isoformat()


def _sources(node: dict) -> tuple[t.MediaSource, ...]:
    """Every file Meta actually hands us a url for.

    A source without a url is not a source. Business Discovery omits
    `media_url` entirely for reels -- confirmed live against several
    accounts -- and keeping an empty string here only defers the problem to
    the http client, which reports it as a malformed url rather than as
    something Meta declined to expose.

    `child_idx` stays the position in the carousel, so dropping a slide
    never renumbers the ones around it.
    """
    children = _children(node)
    if children:
        return tuple(
            t.MediaSource(
                child_idx=index,
                url=child["media_url"],
                mime=_mime(child.get("media_type", "")),
                is_video=child.get("media_type") == "VIDEO",
            )
            for index, child in enumerate(children, start=1)
            if child.get("media_url")
        )
    media_type = node.get("media_type", "")
    if not node.get("media_url"):
        return ()
    return (
        t.MediaSource(
            child_idx=0,
            url=node["media_url"],
            mime=_mime(media_type),
            is_video=media_type == "VIDEO",
        ),
    )


def _thumb_url(node: dict) -> str:
    if node.get("media_type") == "VIDEO":
        return node.get("thumbnail_url") or node.get("media_url") or ""
    children = _children(node)
    if children and not node.get("media_url"):
        first = children[0]
        if first.get("media_type") == "VIDEO":
            return first.get("thumbnail_url") or ""
        return first.get("media_url") or ""
    return node.get("media_url") or ""


def post_from_node(node: dict) -> t.IgPost:
    permalink = node.get("permalink") or ""
    media_type = node.get("media_type", "")
    kind = _KIND.get(media_type, "image")
    # Meta labels the surface a post was published to. A reel can carry a
    # /p/ permalink, so the url shape is only ever a guess at this.
    if kind == "video" and node.get("media_product_type") == "REELS":
        kind = "reel"
    children = _children(node)
    return t.IgPost(
        shortcode=shortcode_from_permalink(permalink),
        kind=kind,
        taken_at_iso=_timestamp(node["timestamp"]),
        caption=node.get("caption") or "",
        is_video=media_type == "VIDEO",
        child_count=len(children) or 1,
        thumb_url=_thumb_url(node),
        ig_url=permalink,
        sources=_sources(node),
        # Absent rather than zero: a photo has no view count at all, and
        # printing 0 would claim nobody watched it.
        like_count=node.get("like_count"),
        comments_count=node.get("comments_count"),
        view_count=node.get("view_count"),
    )


def page_from_payload(payload: dict) -> t.IgPage:
    media = (payload.get("business_discovery") or {}).get("media") or {}
    posts = [post_from_node(node) for node in media.get("data") or []]
    paging = media.get("paging") or {}
    # The nested media edge never sends `paging.next` -- only `cursors.after`,
    # and it sends that even when nothing follows. So the page's own contents
    # are the signal: keep walking while posts come back, and stop on the
    # first empty page. That costs one extra request at the end of a profile
    # and is the only honest terminator Meta offers here.
    cursor = (paging.get("cursors") or {}).get("after") if posts else None
    return t.IgPage(posts=posts, next_cursor=cursor)
