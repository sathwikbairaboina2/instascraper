"""What we have spent against our own limits, and when that frees up.

Not Instagram's accounting -- ours. Because we own the ledger, the reset
time is exact rather than estimated, which is the whole reason the header
can show a countdown here and cannot for Meta's quota.
"""

import sqlite3
from datetime import datetime, timedelta

REEL = "reel_download"

# Old rows are worth keeping briefly -- they answer "what did this thing do
# last night" -- but nothing reads past the widest window.
_KEEP_SECONDS = 7 * 86400


def iso_minus(now: str, seconds: int) -> str:
    return (datetime.fromisoformat(now) - timedelta(seconds=seconds)).isoformat()


def record(conn: sqlite3.Connection, kind: str, now: str) -> None:
    conn.execute("INSERT INTO quota_events (kind, at) VALUES (?,?)", (kind, now))
    conn.execute(
        "DELETE FROM quota_events WHERE at <= ?", (iso_minus(now, _KEEP_SECONDS),)
    )


def count(conn: sqlite3.Connection, kind: str, since: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM quota_events WHERE kind=? AND at > ?", (kind, since)
    ).fetchone()["c"]


def window(
    conn: sqlite3.Connection, kind: str, seconds: int, limit: int, now: str
) -> dict:
    """Usage inside one rolling window, and when the oldest entry leaves it.

    `at > ?` rather than `>=`: an event exactly one window old has aged out.
    """
    since = iso_minus(now, seconds)
    row = conn.execute(
        "SELECT COUNT(*) c, MIN(at) oldest FROM quota_events WHERE kind=? AND at > ?",
        (kind, since),
    ).fetchone()
    oldest = row["oldest"]
    resets_at = (
        (datetime.fromisoformat(oldest) + timedelta(seconds=seconds)).isoformat()
        if oldest
        else None
    )
    return {"used": row["c"], "max": limit, "resets_at": resets_at}
