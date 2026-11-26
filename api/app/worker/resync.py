"""Scheduled re-sync of tracked profiles.

Only queues work: the sync itself still runs through the worker, pacer and
breaker like any other Instagram call.
"""

import logging
import sqlite3
from datetime import datetime, time as dtime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services import activity
from app.worker import queue
from app.worker.breaker import Breaker

log = logging.getLogger("worker.resync")

IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - no tz database in the image
        log.warning("timezone %s unavailable; using %s", name, "IST" if name == "Asia/Kolkata" else "UTC")
        return IST if name == "Asia/Kolkata" else timezone.utc


def _parse_hhmm(text: str) -> dtime:
    hh, mm = text.split(":")
    return dtime(int(hh), int(mm))


def slot_start(now: datetime, daily_at: str, tz_name: str) -> datetime:
    """The latest daily slot at or before now, in UTC (may be yesterday's)."""
    zone = _zone(tz_name)
    local = now.astimezone(zone)
    slot = datetime.combine(local.date(), _parse_hhmm(daily_at), tzinfo=zone)
    if slot > local:
        slot = datetime.combine(local.date() - timedelta(days=1), _parse_hhmm(daily_at), tzinfo=zone)
    return slot.astimezone(timezone.utc)


def next_slot(now: datetime, daily_at: str, tz_name: str) -> datetime:
    """The first daily slot strictly after now, in UTC."""
    zone = _zone(tz_name)
    last = slot_start(now, daily_at, tz_name).astimezone(zone)
    nxt = datetime.combine(last.date() + timedelta(days=1), _parse_hhmm(daily_at), tzinfo=zone)
    return nxt.astimezone(timezone.utc)


def due_since(conn: sqlite3.Connection, cutoff: datetime) -> list[str]:
    """Tracked usernames never synced or last synced before the cutoff, oldest first."""
    rows = conn.execute(
        "SELECT username, last_synced_at FROM profiles WHERE tracked=1"
        " ORDER BY last_synced_at IS NOT NULL, last_synced_at, username"
    ).fetchall()
    return [
        r["username"]
        for r in rows
        if r["last_synced_at"] is None or datetime.fromisoformat(r["last_synced_at"]) < cutoff
    ]


def resync_status(conn: sqlite3.Connection, settings: Settings, now: datetime) -> dict:
    """What GET /api/status shows under `resync`."""
    next_due = None
    if settings.resync_daily_at:
        mode = "daily"
        due = due_since(conn, slot_start(now, settings.resync_daily_at, settings.resync_tz))
    elif settings.resync_interval_hours > 0:
        mode = "interval"
        due = due_profiles(conn, now.isoformat(), settings.resync_interval_hours)
    else:
        mode, due = "off", []
    if due:
        row = conn.execute(
            "SELECT last_synced_at FROM profiles WHERE username=?", (due[0],)
        ).fetchone()
        next_due = {"username": due[0], "last_synced_at": row["last_synced_at"]}
    return {
        "mode": mode,
        "daily_at": settings.resync_daily_at or None,
        "tz": settings.resync_tz if settings.resync_daily_at else None,
        "slot_next": next_slot(now, settings.resync_daily_at, settings.resync_tz).isoformat()
        if settings.resync_daily_at
        else None,
        "interval_hours": settings.resync_interval_hours,
        "check_seconds": settings.resync_check_seconds,
        "next_due": next_due,
    }


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
    """Queue profile_syncs that are due; the first username queued, or None.

    Daily mode queues every profile not synced since today's slot (once the
    slot has passed), oldest first; interval mode queues the most overdue one.
    """
    if settings.resync_daily_at:
        if breaker.wait_seconds() > 0:
            return None
        cutoff = slot_start(now, settings.resync_daily_at, settings.resync_tz)
        queued = []
        for username in due_since(conn, cutoff):
            if queue.enqueue_unique(conn, "profile_sync", {"username": username}) is not None:
                activity.record(conn, "resync", username, None)
                queued.append(username)
        return queued[0] if queued else None
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
