import shutil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.main_deps import get_conn_dep, wake_worker
from app.services import activity
from app.worker import queue

router = APIRouter()


class TrackedBody(BaseModel):
    tracked: bool


def _last_error(conn, username: str) -> str | None:
    row = conn.execute(
        "SELECT error FROM jobs WHERE kind='profile_sync'"
        " AND json_extract(payload, '$.username')=? AND status='failed'"
        " ORDER BY id DESC LIMIT 1",
        (username,),
    ).fetchone()
    return row["error"] if row else None


def _media_summary(row) -> dict:
    return {
        "shortcode": row["shortcode"],
        "kind": row["kind"],
        "taken_at": row["taken_at"],
        "caption": row["caption"],
        "is_video": bool(row["is_video"]),
        "child_count": row["child_count"],
        "full_status": row["full_status"],
        "thumb_url": f"/api/media/{row['shortcode']}/thumb",
        "ig_url": row["ig_url"],
    }


@router.get("/profiles")
def list_profiles(conn=Depends(get_conn_dep)):
    rows = conn.execute(
        "SELECT * FROM profiles WHERE tracked=1 ORDER BY username"
    ).fetchall()
    return {
        "items": [
            {
                "username": r["username"],
                "full_name": r["full_name"],
                "post_count": r["post_count"],
                "avatar_url": f"/api/profiles/{r['username']}/avatar",
                "last_synced_at": r["last_synced_at"],
            }
            for r in rows
        ]
    }


@router.get("/profiles/{username}")
def get_profile(username: str, conn=Depends(get_conn_dep)):
    row = conn.execute("SELECT * FROM profiles WHERE username=?", (username,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"{username} has not been synced",
                "last_error": _last_error(conn, username),
            },
        )
    cached = conn.execute(
        "SELECT COUNT(*) c FROM media_items WHERE username=? AND full_status='ready'",
        (username,),
    ).fetchone()["c"]
    return {
        "username": row["username"],
        "full_name": row["full_name"],
        "biography": row["biography"],
        "is_private": bool(row["is_private"]),
        "post_count": row["post_count"],
        "avatar_url": f"/api/profiles/{username}/avatar",
        "tracked": bool(row["tracked"]),
        "last_synced_at": row["last_synced_at"],
        "exhausted": row["next_cursor"] == "",
        "cached_count": cached,
    }


@router.get("/profiles/{username}/avatar")
def get_avatar(username: str, request: Request, conn=Depends(get_conn_dep)):
    row = conn.execute(
        "SELECT avatar_path FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row is None or not row["avatar_path"]:
        raise HTTPException(status_code=404, detail={"message": "no avatar cached"})
    path = request.app.state.settings.media_dir / row["avatar_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "avatar file missing"})
    return FileResponse(path, media_type="image/jpeg")


@router.post("/profiles/{username}/sync")
def sync_profile(username: str, request: Request, conn=Depends(get_conn_dep)):
    job_id = queue.enqueue_unique(conn, "profile_sync", {"username": username})
    activity.record(conn, "lookup", username, None)
    wake_worker(request)
    return {"queued": job_id is not None}


@router.put("/profiles/{username}/tracked")
def set_tracked(username: str, body: TrackedBody, conn=Depends(get_conn_dep)):
    cur = conn.execute(
        "UPDATE profiles SET tracked=? WHERE username=?", (int(body.tracked), username)
    )
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    activity.record(conn, "track" if body.tracked else "untrack", username, None)
    return {"tracked": body.tracked}


@router.get("/profiles/{username}/media")
def list_media(
    username: str,
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    profile = conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    total = conn.execute(
        "SELECT COUNT(*) c FROM media_items WHERE username=?", (username,)
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM media_items WHERE username=?"
        " ORDER BY taken_at DESC, shortcode LIMIT ? OFFSET ?",
        (username, limit, offset),
    ).fetchall()
    return {
        "items": [_media_summary(r) for r in rows],
        "total": total,
        "exhausted": profile["next_cursor"] == "",
    }


@router.post("/profiles/{username}/load-more")
def load_more(username: str, request: Request, conn=Depends(get_conn_dep)):
    profile = conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    if profile["next_cursor"] == "":
        return {"queued": False, "exhausted": True}
    job_id = queue.enqueue_unique(conn, "page_fetch", {"username": username})
    activity.record(conn, "load_more", username, None)
    wake_worker(request)
    return {"queued": job_id is not None, "exhausted": False}


@router.delete("/profiles/{username}/cache")
def clear_cache(username: str, request: Request, conn=Depends(get_conn_dep)):
    media_root = request.app.state.settings.media_dir
    target = media_root / username
    removed = 0
    if target.exists():
        removed = sum(1 for p in target.rglob("*") if p.is_file())
        shutil.rmtree(target)
    conn.execute(
        "DELETE FROM media_files WHERE shortcode IN"
        " (SELECT shortcode FROM media_items WHERE username=?)",
        (username,),
    )
    conn.execute(
        "UPDATE media_items SET full_status='none', full_error=NULL WHERE username=?",
        (username,),
    )
    conn.execute("UPDATE profiles SET avatar_path=NULL WHERE username=?", (username,))
    return {"removed_files": removed}
