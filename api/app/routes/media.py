from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.main_deps import get_conn_dep, wake_worker
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


@router.post("/media/ensure")
def ensure(body: EnsureBody, request: Request, conn=Depends(get_conn_dep)):
    statuses: dict[str, str] = {}
    errors: dict[str, str] = {}
    enqueued = False

    for shortcode in body.shortcodes:
        item = conn.execute(
            "SELECT full_status, full_error FROM media_items WHERE shortcode=?",
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
