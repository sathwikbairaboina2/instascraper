"""What subjects are doing well right now.

A read-only view over media_items. Nothing here writes, and nothing here
talks to Instagram: the ranking is computed from captions and engagement
that a sync already brought in.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.main_deps import get_conn_dep
from app.services import hashtags
from app.services.media_view import media_summary

router = APIRouter()


def _since(window: str) -> str:
    """The cutoff, or a 400 naming what was asked for.

    Falling back to a default window would answer a typo with real-looking
    numbers for a period nobody asked about.
    """
    try:
        return hashtags.window_since(window)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unknown window: {window}",
                "allowed": sorted(hashtags.WINDOWS),
            },
        ) from None


@router.get("/hashtags/trending")
def trending(
    window: str = Query("day"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    since = _since(window)
    # taken_at is ISO-8601 UTC with a +00:00 offset from every writer, so a
    # string comparison is a chronological one.
    rows = conn.execute(
        "SELECT caption, like_count, comments_count, view_count"
        " FROM media_items WHERE taken_at >= ?",
        (since,),
    ).fetchall()

    items = hashtags.rank(rows)
    return {
        "window": window,
        "since": since,
        "total": len(items),
        "items": items[offset : offset + limit],
    }


@router.get("/hashtags/{tag}/posts")
def tag_posts(
    tag: str,
    window: str = Query("day"),
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    """The posts carrying one tag, newest first.

    A tag nobody used is an empty list rather than a 404: a tag that has
    fallen out of the window is not an error, and this endpoint cannot
    honestly tell that case apart from one that never existed.
    """
    since = _since(window)
    wanted = tag.lstrip("#").casefold()

    rows = conn.execute(
        "SELECT * FROM media_items WHERE taken_at >= ?"
        " ORDER BY taken_at DESC, shortcode",
        (since,),
    ).fetchall()
    matched = [r for r in rows if wanted in hashtags.extract_tags(r["caption"])]

    return {
        "tag": wanted,
        "window": window,
        "total": len(matched),
        "items": [media_summary(r) for r in matched[offset : offset + limit]],
    }
