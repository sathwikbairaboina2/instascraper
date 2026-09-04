"""Posts lined up to be remade as our own content.

Deliberately not a view over `media_items`. An entry here is queued work: it
snapshots what a generator will need at the moment it is marked, so clearing
a profile's cache, or its rows going away, cannot quietly delete something
already lined up. The cost is that a caption edited on Instagram afterwards
will not follow -- which for "remake the thing I saw" is the right way round.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.clock import now_iso
from app.main_deps import get_conn_dep
from app.probe import dimensions

router = APIRouter()

# Thin on purpose. The service that will move an item through these does not
# exist yet, and inventing states for behaviour nobody has decided on earns a
# migration on the day it lands.
SELECTED = "selected"
# Files on disk and a payload built, nothing handed over. Calling this
# "submitted" would claim a handoff that has not happened -- that word is
# earned when the job reaches the creator's queue.
PREPARED = "prepared"
# The payload has reached instacreator's queue. Earned, not assumed: the
# status flips only after the queue accepted the message.
SUBMITTED = "submitted"


class MarkBody(BaseModel):
    shortcodes: list[str]


class PrepareBody(BaseModel):
    # None means "whatever the post has": a single post has no choice to
    # make, and a carousel defaults to all of it.
    slides: list[int] | None = None


def _row(r) -> dict:
    return {
        "shortcode": r["shortcode"],
        "username": r["username"],
        "ig_url": r["ig_url"],
        "caption": r["caption"],
        "status": r["status"],
        "error": r["error"],
        "added_at": r["added_at"],
        "prepared_at": r["prepared_at"],
        "payload": json.loads(r["payload"]) if r["payload"] else None,
        "thumb_url": f"/api/media/{r['shortcode']}/thumb",
    }


@router.post("/recreate")
def mark(body: MarkBody, conn=Depends(get_conn_dep)):
    added = 0
    unknown: list[str] = []
    now = now_iso()

    for shortcode in body.shortcodes:
        item = conn.execute(
            "SELECT username, ig_url, caption FROM media_items WHERE shortcode=?",
            (shortcode,),
        ).fetchone()
        if item is None:
            # Say so rather than writing a row with nothing in it: an entry
            # that cannot name its source is not work anyone can do.
            unknown.append(shortcode)
            continue

        cur = conn.execute(
            "INSERT INTO recreate_items"
            " (shortcode, username, ig_url, caption, status, added_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(shortcode) DO NOTHING",
            (shortcode, item["username"], item["ig_url"], item["caption"], SELECTED, now, now),
        )
        added += cur.rowcount

    return {"added": added, "unknown": unknown}


@router.get("/recreate")
def list_items(conn=Depends(get_conn_dep)):
    rows = conn.execute(
        "SELECT * FROM recreate_items ORDER BY added_at DESC, shortcode"
    ).fetchall()
    return {"items": [_row(r) for r in rows]}


@router.get("/recreate/{shortcode}")
def get_item(shortcode: str, conn=Depends(get_conn_dep)):
    row = conn.execute(
        "SELECT * FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "not marked for recreation"})
    return _row(row)


@router.delete("/recreate/{shortcode}")
def unmark(shortcode: str, conn=Depends(get_conn_dep)):
    cur = conn.execute("DELETE FROM recreate_items WHERE shortcode=?", (shortcode,))
    return {"removed": cur.rowcount}


def _backfill_dimensions(conn, media_dir, shortcode: str, files: dict) -> None:
    """Read the size of any file whose row does not know it, and store it.

    Rows written before the probe existed carry NULL here, and nothing else
    ever revisits a file already on disk -- so the payload shipped
    `"width": null` forever, which is exactly the thing the probe exists to
    prevent. Reading a header is cheap; doing it once and remembering is
    cheaper.
    """
    for child_idx, row in list(files.items()):
        if row["width"] is not None and row["height"] is not None:
            continue
        path = media_dir / row["path"]
        if not path.exists():
            continue
        size = dimensions(path)
        if size is None:
            continue
        width, height = size
        conn.execute(
            "UPDATE media_files SET width=?, height=? WHERE shortcode=? AND role='full'"
            " AND child_idx=?",
            (width, height, shortcode, child_idx),
        )
        files[child_idx] = {**dict(row), "width": width, "height": height}


@router.post("/recreate/{shortcode}/prepare")
def prepare(
    shortcode: str, body: PrepareBody, request: Request, conn=Depends(get_conn_dep)
):
    """Build the handoff payload from what is actually on disk.

    Every path in it is one we have just read out of media_files, so the
    payload cannot name a file that was never downloaded.
    """
    item = conn.execute(
        "SELECT * FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail={"message": "not marked for recreation"})

    media = conn.execute(
        "SELECT kind, taken_at, child_count, full_status FROM media_items WHERE shortcode=?",
        (shortcode,),
    ).fetchone()
    if media is None or media["full_status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={"message": "the post is not downloaded yet; fetch it before preparing"},
        )

    files = {
        int(r["child_idx"]): r
        for r in conn.execute(
            "SELECT child_idx, path, mime, bytes, width, height FROM media_files"
            " WHERE shortcode=? AND role='full' ORDER BY child_idx",
            (shortcode,),
        )
    }
    if not files:
        raise HTTPException(
            status_code=409,
            detail={"message": "the post is not downloaded yet; fetch it before preparing"},
        )

    media_dir = request.app.state.runtime.current.settings.media_dir
    _backfill_dimensions(conn, media_dir, shortcode, files)

    wanted = sorted(files) if body.slides is None else sorted(set(body.slides))
    missing = [i for i in wanted if i not in files]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"no such slide: {', '.join(str(i) for i in missing)}",
                "available": sorted(files),
            },
        )

    now = now_iso()
    payload = {
        "shortcode": shortcode,
        "username": item["username"],
        "ig_url": item["ig_url"],
        "caption": item["caption"],
        "kind": media["kind"],
        "taken_at": media["taken_at"],
        "prepared_at": now,
        "slides": [
            {
                "index": i,
                # Relative to the media root. An absolute path leaks a home
                # directory into a payload that gets passed around, and is no
                # more usable to anything running elsewhere.
                "path": files[i]["path"],
                "mime": files[i]["mime"],
                "bytes": files[i]["bytes"],
                "width": files[i]["width"],
                "height": files[i]["height"],
            }
            for i in wanted
        ],
    }

    conn.execute(
        "UPDATE recreate_items SET status=?, slides=?, payload=?, prepared_at=?,"
        " updated_at=?, error=NULL WHERE shortcode=?",
        (PREPARED, json.dumps(wanted), json.dumps(payload), now, now, shortcode),
    )
    return payload


@router.post("/recreate/{shortcode}/submit")
def submit(shortcode: str, request: Request, conn=Depends(get_conn_dep)):
    """Publish a prepared payload to instacreator's queue.

    Resubmitting is allowed on purpose: the receiver dedupes on source_ref,
    and a lost message must have a recovery gesture cheaper than re-preparing.
    """
    item = conn.execute(
        "SELECT status, payload FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail={"message": "not marked for recreation"})
    if item["status"] not in (PREPARED, SUBMITTED) or not item["payload"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "prepare the item before submitting it"},
        )

    publisher = request.app.state.publisher
    if not publisher.configured:
        raise HTTPException(
            status_code=503,
            detail={"message": "no queue configured; set SQS_ENDPOINT to enable the handoff"},
        )

    from app.services.submit import envelope_from_payload

    publisher.publish(envelope_from_payload(json.loads(item["payload"])))
    conn.execute(
        "UPDATE recreate_items SET status=?, updated_at=? WHERE shortcode=?",
        (SUBMITTED, now_iso(), shortcode),
    )
    return {"status": SUBMITTED, "shortcode": shortcode}
