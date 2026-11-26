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


# ---- daily window ------------------------------------------------------
# 06:00 Asia/Kolkata is 00:30 UTC.
from app.worker.resync import next_slot, slot_start  # noqa: E402


def _daily(settings, **kw):
    return replace(settings, resync_daily_at="06:00", resync_tz="Asia/Kolkata", **kw)


def _at(day, hh, mm):
    return datetime(2026, 11, day, hh, mm, tzinfo=timezone.utc)


def _stamp(conn, name, when):
    conn.execute("UPDATE profiles SET last_synced_at=? WHERE username=?", (when.isoformat(), name))


def test_daily_defaults_and_env(monkeypatch):
    monkeypatch.delenv("RESYNC_DAILY_AT", raising=False)
    monkeypatch.delenv("RESYNC_TZ", raising=False)
    s = load_settings()
    assert s.resync_daily_at == "06:00"
    assert s.resync_tz == "Asia/Kolkata"
    monkeypatch.setenv("RESYNC_DAILY_AT", "")
    monkeypatch.setenv("RESYNC_TZ", "UTC")
    s = load_settings()
    assert s.resync_daily_at == ""
    assert s.resync_tz == "UTC"


def test_slot_math_in_the_zone():
    # 23 Nov 00:29 UTC is 05:59 IST: today's slot has not come, yesterday's is the last.
    assert slot_start(_at(23, 0, 29), "06:00", "Asia/Kolkata") == _at(22, 0, 30)
    assert slot_start(_at(23, 0, 30), "06:00", "Asia/Kolkata") == _at(23, 0, 30)
    # 19:00 UTC on the 22nd is 00:30 IST on the 23rd, past midnight in the zone.
    assert slot_start(_at(22, 19, 0), "06:00", "Asia/Kolkata") == _at(22, 0, 30)
    assert next_slot(_at(23, 0, 29), "06:00", "Asia/Kolkata") == _at(23, 0, 30)
    assert next_slot(_at(23, 0, 30), "06:00", "Asia/Kolkata") == _at(24, 0, 30)


def test_daily_before_slot_queues_nothing(settings, conn):
    s = _daily(settings)
    _profile(conn, "a", synced_hours_ago=30)
    # Today's slot (00:30 UTC) has not come; the profile was synced after
    # yesterday's, so it is not due.
    _stamp(conn, "a", _at(22, 1, 0))
    assert resync_tick(conn, s, Breaker(), _at(23, 0, 29)) is None
    assert queue.depth(conn) == 0


def test_daily_after_slot_queues_all_oldest_first_once(settings, conn):
    s = _daily(settings)
    _profile(conn, "a", synced_hours_ago=30)
    _profile(conn, "b", synced_hours_ago=50)
    _profile(conn, "never", synced_hours_ago=None)
    _profile(conn, "fresh", synced_hours_ago=None)
    _stamp(conn, "fresh", _at(23, 0, 45))  # synced after the slot
    now = _at(23, 1, 0)
    breaker = Breaker()
    assert resync_tick(conn, s, breaker, now) == "never"
    rows = conn.execute("SELECT payload FROM jobs ORDER BY id").fetchall()
    assert [r["payload"] for r in rows] == [
        '{"username": "never"}', '{"username": "b"}', '{"username": "a"}'
    ]
    # Same tick again: everything is already pending.
    assert resync_tick(conn, s, breaker, now) is None
    assert queue.depth(conn) == 3


def test_daily_again_next_day(settings, conn):
    s = _daily(settings)
    _profile(conn, "a", synced_hours_ago=None)
    assert resync_tick(conn, s, Breaker(), _at(23, 1, 0)) == "a"
    conn.execute("DELETE FROM jobs")
    _stamp(conn, "a", _at(23, 1, 5))
    assert resync_tick(conn, s, Breaker(), _at(23, 12, 0)) is None
    assert resync_tick(conn, s, Breaker(), _at(24, 1, 0)) == "a"


def test_daily_breaker_skips(settings, conn):
    s = _daily(settings)
    _profile(conn, "a", synced_hours_ago=None)
    breaker = Breaker()
    breaker.trip_temporary(60, "429")
    assert resync_tick(conn, s, breaker, _at(23, 1, 0)) is None
    assert queue.depth(conn) == 0


def test_interval_mode_when_daily_off(settings, conn):
    s = replace(settings, resync_daily_at="")
    _profile(conn, "a", synced_hours_ago=50)
    _profile(conn, "b", synced_hours_ago=40)
    assert resync_tick(conn, s, Breaker(), NOW) == "a"
    assert queue.depth(conn) == 1


def test_resync_status_shapes(settings, conn):
    from app.worker.resync import resync_status

    s = _daily(settings)
    _profile(conn, "a", synced_hours_ago=None)
    st = resync_status(conn, s, _at(23, 1, 0))
    assert st["mode"] == "daily"
    assert st["daily_at"] == "06:00" and st["tz"] == "Asia/Kolkata"
    assert st["next_due"]["username"] == "a"
    off = replace(settings, resync_daily_at="")
    st = resync_status(conn, off, _at(23, 1, 0))
    assert st["mode"] == "interval" and st["daily_at"] is None
    st = resync_status(conn, replace(off, resync_interval_hours=0.0), _at(23, 1, 0))
    assert st["mode"] == "off"
