"""Posts lined up to be remade as our own content.

Deliberately not a view over `media_items`. An entry here is queued work: it
snapshots what a generator will need at the moment it is marked, so clearing
a profile's cache, or its rows going away, cannot quietly delete something
already lined up. The cost is that a caption edited on Instagram afterwards
will not follow -- which for "remake the thing I saw" is the right way round.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.clock import now_iso
from app.main_deps import get_conn_dep

router = APIRouter()

# Thin on purpose. The service that will move an item through these does not
# exist yet, and inventing states for behaviour nobody has decided on earns a
# migration on the day it lands.
SELECTED = "selected"


class MarkBody(BaseModel):
    shortcodes: list[str]


def _row(r) -> dict:
    return {
        "shortcode": r["shortcode"],
        "username": r["username"],
        "ig_url": r["ig_url"],
        "caption": r["caption"],
        "status": r["status"],
        "error": r["error"],
        "added_at": r["added_at"],
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
