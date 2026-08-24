"""Hashtags read out of captions, and ranked by how well their posts did.

Nothing is stored. The window in front of every query bounds the scan to
recent posts, which is a small slice of media_items however large that
table gets. If that ever stops being true, these functions are pure enough
that a materialised index can be swapped in underneath them.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone

# A '#' counts at the start of the caption or after whitespace, and nowhere
# else. Without that guard, 'example.com/#anchor' becomes a trending tag.
#
# The body is grabbed whole and trimmed by _body() rather than matched by a
# character class, because `\w` excludes combining marks: it cuts a
# Devanagari tag at its first vowel sign, so #नाइकी indexes as #न. Getting
# that wrong does not fail loudly -- it quietly makes the feature
# Latin-only.
_TAG = re.compile(r"(?:^|\s)#(\S+)")

# Letters, numbers and marks. Marks are the reason this is a category test
# and not a regex class. `Pc` is underscore and its relatives, which
# Instagram allows inside a tag.
_KEEP = ("L", "N", "M")


def _body(raw: str) -> str:
    """The tag out of the run of characters that followed a '#'.

    Stops at the first character that cannot be part of a tag, which is what
    makes '#nike,' and '#fit!' come back without their punctuation.
    """
    out: list[str] = []
    for ch in raw:
        category = unicodedata.category(ch)
        if category[0] in _KEEP or category == "Pc":
            out.append(ch)
        else:
            break
    return "".join(out)

WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
}


def extract_tags(caption: str | None) -> list[str]:
    """Every distinct tag in one caption, case-folded, first-seen order.

    Deduped per post on purpose: a caption repeating '#sale' three times
    should not outrank a post people actually engaged with.
    """
    if not caption:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _TAG.finditer(caption):
        # casefold, not lower: it is what makes Greek 'ΚΌΣΜΟΣ', 'κόσμος' and
        # 'κόσμοσ' one tag rather than three. The cost is that the stored
        # form of a Greek tag ends in a non-final sigma.
        tag = _body(match.group(1)).casefold()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def window_since(window: str, now: datetime | None = None) -> str:
    """The cutoff for a window, as an ISO string comparable to taken_at."""
    delta = WINDOWS.get(window)
    if delta is None:
        raise ValueError(f"unknown window: {window}")
    moment = now or datetime.now(timezone.utc)
    return (moment - delta).isoformat()


def rank(rows: Iterable[Mapping]) -> list[dict]:
    """Aggregate rows into a ranked list of tags.

    The sort has three keys because paging is offset-based: without a total
    order, two rows that compare equal can swap between requests and make a
    page repeat an entry or drop one.
    """
    totals: dict[str, dict] = {}

    for row in rows:
        tags = extract_tags(row["caption"])
        if not tags:
            continue
        likes = row["like_count"] or 0
        comments = row["comments_count"] or 0
        views = row["view_count"] or 0
        for tag in tags:
            entry = totals.get(tag)
            if entry is None:
                entry = totals[tag] = {
                    "tag": tag,
                    "score": 0,
                    "like_count": 0,
                    "comments_count": 0,
                    "view_count": 0,
                    "post_count": 0,
                }
            entry["like_count"] += likes
            entry["comments_count"] += comments
            entry["view_count"] += views
            entry["score"] += likes + comments + views
            entry["post_count"] += 1

    return sorted(
        totals.values(),
        key=lambda i: (-i["score"], -i["post_count"], i["tag"]),
    )
