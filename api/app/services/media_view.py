"""One post, in the shape the media grid consumes.

Lived in routes/profiles.py until a second route needed the same rows. Two
serializers for one grid drift, and the drift shows up as a field the UI
silently reads as undefined.
"""

import json


def video_children(row) -> list[int]:
    """Which slides of a carousel are video.

    `is_video` describes the post, and a carousel is never one even when it
    holds a video slide. Without this the viewer has no way to tell which
    child to render as video, so it renders every slide as an image and the
    video ones break.
    """
    try:
        entries = json.loads(row["src_urls"] or "[]")
    except (TypeError, ValueError):
        return []
    return [int(e["child_idx"]) for e in entries if e.get("is_video")]


def media_summary(row) -> dict:
    return {
        "shortcode": row["shortcode"],
        "kind": row["kind"],
        "taken_at": row["taken_at"],
        "caption": row["caption"],
        "is_video": bool(row["is_video"]),
        "video_children": video_children(row),
        "child_count": row["child_count"],
        "like_count": row["like_count"],
        "comments_count": row["comments_count"],
        "view_count": row["view_count"],
        "full_status": row["full_status"],
        "full_error": row["full_error"],
        "thumb_url": f"/api/media/{row['shortcode']}/thumb",
        "ig_url": row["ig_url"],
    }
