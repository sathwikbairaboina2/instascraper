"""Posts reached by pasting a link rather than by walking a profile.

`direct_urls` is a membership list, not a copy of the post: the fetched media
lands in `media_items`/`media_files` exactly as profile posts do, so download,
ensure and recreate work on it unchanged. Removing an entry here forgets the
bookmark and keeps the media.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.clock import now_iso
from app.main_deps import get_conn_dep, wake_worker
from app.services import activity
from app.services.media_view import media_summary
from app.services.urls import parse_shortcode
from app.worker import queue

router = APIRouter()


class AddBody(BaseModel):
    urls: list[str]


def _fetch_state(conn, shortcode: str) -> tuple[str, str | None]:
    """('pending'|'failed', error) from the newest url_fetch job.

    The newest job decides: a failure followed by a re-queue is pending
    again, not a stale error frozen on screen.
    """
    row = conn.execute(
        "SELECT status, error FROM jobs WHERE kind='url_fetch'"
        " AND json_extract(payload, '$.shortcode')=?"
        " ORDER BY id DESC LIMIT 1",
        (shortcode,),
    ).fetchone()
    if row is not None and row["status"] == "failed":
        return "failed", row["error"]
    return "pending", None


@router.post("/urls")
def add_urls(body: AddBody, request: Request, conn=Depends(get_conn_dep)):
    added: list[str] = []
    invalid: list[str] = []
    now = now_iso()

    for raw in body.urls:
        text = raw.strip()
        if not text:
            continue
        shortcode = parse_shortcode(text)
        if shortcode is None:
            invalid.append(raw)
            continue
        cur = conn.execute(
            "INSERT INTO direct_urls (shortcode, url, added_at) VALUES (?,?,?)"
            " ON CONFLICT(shortcode) DO NOTHING",
            (shortcode, text, now),
        )
        if cur.rowcount:
            added.append(shortcode)
            queue.enqueue_unique(conn, "url_fetch", {"shortcode": shortcode, "url": text})
            activity.record(conn, "direct_url", shortcode, None)
            continue

        # Already on the list. Pasting the link again is the retry gesture,
        # so a post that never landed gets its fetch queued once more;
        # enqueue_unique keeps a second paste while one is queued harmless.
        ready = conn.execute(
            "SELECT 1 FROM media_items WHERE shortcode=? AND full_status='ready'",
            (shortcode,),
        ).fetchone()
        if ready is None:
            job_id = queue.enqueue_unique(
                conn, "url_fetch", {"shortcode": shortcode, "url": text}
            )
            if job_id is not None:
                added.append(shortcode)

    if added:
        wake_worker(request)
    return {"added": added, "invalid": invalid}


@router.get("/urls")
def list_urls(conn=Depends(get_conn_dep)):
    rows = conn.execute(
        "SELECT d.shortcode, d.url, d.added_at, m.username, m.shortcode AS media_sc"
        " FROM direct_urls d LEFT JOIN media_items m ON m.shortcode=d.shortcode"
        " ORDER BY d.added_at DESC, d.shortcode"
    ).fetchall()

    items = []
    for r in rows:
        base = {"shortcode": r["shortcode"], "url": r["url"], "added_at": r["added_at"]}
        if r["media_sc"] is not None:
            media = conn.execute(
                "SELECT * FROM media_items WHERE shortcode=?", (r["shortcode"],)
            ).fetchone()
            items.append(
                {
                    **base,
                    "status": "indexed",
                    "username": r["username"],
                    "error": None,
                    "media": media_summary(media),
                }
            )
            continue
        status, error = _fetch_state(conn, r["shortcode"])
        items.append(
            {**base, "status": status, "username": None, "error": error, "media": None}
        )
    return {"items": items}


@router.delete("/urls/{shortcode}")
def remove_url(shortcode: str, conn=Depends(get_conn_dep)):
    cur = conn.execute("DELETE FROM direct_urls WHERE shortcode=?", (shortcode,))
    return {"removed": cur.rowcount}
