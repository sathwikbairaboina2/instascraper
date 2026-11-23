"""Scheduled re-sync of tracked profiles.

Only queues work: the sync itself still runs through the worker, pacer and
breaker like any other Instagram call.
"""

import sqlite3
from datetime import datetime, timedelta

from app.config import Settings
from app.services import activity
from app.worker import queue
from app.worker.breaker import Breaker


def due_profiles(conn: sqlite3.Connection, now_iso: str, interval_hours: float) -> list[str]:
    """Tracked usernames never synced or last synced over the interval ago.

    Never-synced first, then oldest first.
    """
    cutoff = datetime.fromisoformat(now_iso) - timedelta(hours=interval_hours)
    rows = conn.execute(
        "SELECT username, last_synced_at FROM profiles WHERE tracked=1"
        " ORDER BY last_synced_at IS NOT NULL, last_synced_at, username"
    ).fetchall()
    due = []
    for r in rows:
        if r["last_synced_at"] is None or datetime.fromisoformat(r["last_synced_at"]) <= cutoff:
            due.append(r["username"])
    return due


def resync_tick(
    conn: sqlite3.Connection, settings: Settings, breaker: Breaker, now: datetime
) -> str | None:
    """Queue one profile_sync for the most overdue profile; its username, or None."""
    if settings.resync_interval_hours <= 0:
        return None
    if breaker.wait_seconds() > 0:
        return None
    due = due_profiles(conn, now.isoformat(), settings.resync_interval_hours)
    if not due:
        return None
    username = due[0]
    if queue.enqueue_unique(conn, "profile_sync", {"username": username}) is None:
        return None
    activity.record(conn, "resync", username, None)
    return username
