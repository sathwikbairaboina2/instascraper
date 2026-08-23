import sqlite3
from pathlib import Path


def sweep(conn: sqlite3.Connection, media_root: Path) -> dict:
    """Undo the damage of a container killed mid-fetch.

    Runs once on startup, before the worker thread starts.
    """
    parts = 0
    if media_root.exists():
        for leftover in media_root.rglob("*.part"):
            leftover.unlink(missing_ok=True)
            parts += 1

    cur = conn.execute(
        "UPDATE media_items SET full_status='none', full_error=NULL"
        " WHERE full_status IN ('fetching','queued')"
    )
    items = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    cur = conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'"
    )
    jobs = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    return {"parts": parts, "items": items, "jobs": jobs}
