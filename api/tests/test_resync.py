from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.config import load_settings
from app.services import activity
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.resync import due_profiles, resync_tick

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _profile(conn, name, tracked=1, synced_hours_ago=None):
    conn.execute(
        "INSERT INTO profiles (username, tracked, last_synced_at, created_at)"
        " VALUES (?,?,?,?)",
        (name, tracked, None if synced_hours_ago is None else _iso(synced_hours_ago), _iso(100)),
    )


def test_config_defaults_and_env(monkeypatch):
    monkeypatch.delenv("RESYNC_INTERVAL_HOURS", raising=False)
    monkeypatch.delenv("RESYNC_CHECK_SECONDS", raising=False)
    s = load_settings()
    assert s.resync_interval_hours == 24.0
    assert s.resync_check_seconds == 300.0
    monkeypatch.setenv("RESYNC_INTERVAL_HOURS", "0")
    monkeypatch.setenv("RESYNC_CHECK_SECONDS", "2")
    s = load_settings()
    assert s.resync_interval_hours == 0.0
    assert s.resync_check_seconds == 2.0


def test_due_and_not_due(conn):
    _profile(conn, "stale", synced_hours_ago=30)
    _profile(conn, "fresh", synced_hours_ago=2)
    assert due_profiles(conn, NOW.isoformat(), 24) == ["stale"]


def test_nulls_first_then_oldest(conn):
    _profile(conn, "old", synced_hours_ago=48)
    _profile(conn, "older", synced_hours_ago=72)
    _profile(conn, "never", synced_hours_ago=None)
    assert due_profiles(conn, NOW.isoformat(), 24) == ["never", "older", "old"]


def test_untracked_ignored(conn):
    _profile(conn, "loose", tracked=0, synced_hours_ago=None)
    assert due_profiles(conn, NOW.isoformat(), 24) == []


def test_tick_enqueues_one_per_call_and_records_activity(settings, conn):
    _profile(conn, "a", synced_hours_ago=50)
    _profile(conn, "b", synced_hours_ago=40)
    breaker = Breaker()

    assert resync_tick(conn, settings, breaker, NOW) == "a"
    jobs = conn.execute("SELECT kind, payload FROM jobs").fetchall()
    assert [(j["kind"], j["payload"]) for j in jobs] == [("profile_sync", '{"username": "a"}')]
    acts = activity.recent(conn)
    assert acts[0]["action"] == "resync" and acts[0]["target"] == "a"


def test_duplicate_pending_sync_is_not_doubled(settings, conn):
    _profile(conn, "a", synced_hours_ago=50)
    breaker = Breaker()
    assert resync_tick(conn, settings, breaker, NOW) == "a"
    assert resync_tick(conn, settings, breaker, NOW) is None
    assert queue.depth(conn) == 1
    assert len([a for a in activity.recent(conn) if a["action"] == "resync"]) == 1


def test_tripped_breaker_skips(settings, conn):
    _profile(conn, "a", synced_hours_ago=50)
    breaker = Breaker()
    breaker.trip_temporary(60, "429")
    assert resync_tick(conn, settings, breaker, NOW) is None
    assert queue.depth(conn) == 0


def test_disabled_skips(settings, conn):
    _profile(conn, "a", synced_hours_ago=50)
    off = replace(settings, resync_interval_hours=0.0)
    assert resync_tick(conn, off, Breaker(), NOW) is None
    assert queue.depth(conn) == 0
