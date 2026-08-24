import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from app.clock import now_iso
from app.main_deps import get_conn_dep, wake_worker
from app.services import quota
from app.worker import queue

router = APIRouter()


class EnsureBody(BaseModel):
    shortcodes: list[str]
    retry: bool = False


def _file_row(conn, shortcode: str, role: str, child_idx: int):
    return conn.execute(
        "SELECT * FROM media_files WHERE shortcode=? AND role=? AND child_idx=?",
        (shortcode, role, child_idx),
    ).fetchone()


@router.get("/media/{shortcode}/thumb")
def get_thumb(shortcode: str, request: Request, conn=Depends(get_conn_dep)):
    row = _file_row(conn, shortcode, "thumb", 0)
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "no thumbnail cached"})
    path = request.app.state.runtime.current.settings.media_dir / row["path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "thumbnail file missing"})
    return FileResponse(path, media_type=row["mime"] or "image/jpeg")


@router.get("/media/{shortcode}/full")
def get_full(
    shortcode: str,
    request: Request,
    child: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    item = conn.execute(
        "SELECT full_status FROM media_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None or item["full_status"] != "ready":
        raise HTTPException(status_code=404, detail={"message": "not cached"})
    row = _file_row(conn, shortcode, "full", child)
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "no such child"})
    path = request.app.state.runtime.current.settings.media_dir / row["path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "file missing"})
    return FileResponse(
        path,
        media_type=row["mime"] or "application/octet-stream",
        filename=path.name,
        content_disposition_type="inline",
    )


def _reel_cap_spent(conn, settings) -> str | None:
    """The reason the next reel cannot be fetched, or None if it can.

    Read-only: the ledger is spent by the downloader, never by a caller
    deciding whether to offer the action.
    """
    now = now_iso()
    for seconds, limit, label in (
        (3600, settings.reel_max_per_hour, "hourly"),
        (86400, settings.reel_max_per_day, "daily"),
    ):
        state = quota.window(conn, quota.REEL, seconds, limit, now)
        if state["used"] >= limit:
            return f"{label} reel cap spent ({state['used']}/{limit})"
    return None


@router.post("/media/ensure")
def ensure(body: EnsureBody, request: Request, conn=Depends(get_conn_dep)):
    statuses: dict[str, str] = {}
    errors: dict[str, str] = {}
    enqueued = False

    for shortcode in body.shortcodes:
        item = conn.execute(
            "SELECT kind, full_status, full_error FROM media_items WHERE shortcode=?",
            (shortcode,),
        ).fetchone()
        if item is None:
            statuses[shortcode] = "unknown"
            continue

        status = item["full_status"]
        if status == "failed" and body.retry:
            status = "none"
        if status in ("ready", "queued", "fetching", "failed"):
            statuses[shortcode] = status
            if status == "failed":
                errors[shortcode] = item["full_error"] or "unknown error"
            continue

        if item["kind"] == "reel":
            settings = request.app.state.runtime.current.settings
            spent = _reel_cap_spent(conn, settings)
            if spent is not None:
                # Refuse where the click happened. A job queued against a
                # spent cap only fails later, somewhere nobody is looking.
                statuses[shortcode] = "quota"
                errors[shortcode] = spent
                continue

        queue.enqueue_unique(conn, "media_fetch", {"shortcode": shortcode})
        conn.execute(
            "UPDATE media_items SET full_status='queued', full_error=NULL WHERE shortcode=?",
            (shortcode,),
        )
        statuses[shortcode] = "queued"
        enqueued = True

    if enqueued:
        wake_worker(request)

    return {
        "statuses": statuses,
        "errors": errors,
        "ready": sum(1 for s in statuses.values() if s == "ready"),
        "total": len(statuses),
    }


@router.get("/media/{shortcode}/preview")
def get_preview(shortcode: str, child: int = 0, conn=Depends(get_conn_dep)):
    """Point at the source image for one slide, before anything is downloaded.

    Business Discovery hands us a url per child when the post is indexed, so
    a carousel can be previewed slide by slide without spending a download
    first. Those urls expire, which is why this redirects rather than
    promising to serve the bytes: a dead one fails as a broken image the
    caller can fall back from, not as a cached wrong answer.
    """
    row = conn.execute(
        "SELECT src_urls FROM media_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if row is None or not row["src_urls"]:
        raise HTTPException(status_code=404, detail={"message": "no sources recorded"})

    for entry in json.loads(row["src_urls"]):
        if int(entry.get("child_idx", 0)) != child:
            continue
        url = entry.get("url")
        if not url:
            break
        if entry.get("is_video"):
            # A video slide has no still to show; the caller draws its own
            # placeholder rather than being handed an mp4 to put in an img.
            raise HTTPException(status_code=404, detail={"message": "slide is a video"})
        return RedirectResponse(url, status_code=307)

    raise HTTPException(status_code=404, detail={"message": "no such slide"})
