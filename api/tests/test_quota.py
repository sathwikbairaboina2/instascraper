from app.services import quota


def test_counts_only_events_inside_the_window(conn):
    quota.record(conn, quota.REEL, "2026-08-25T10:00:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T10:30:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T11:30:00+00:00")

    now = "2026-08-25T11:45:00+00:00"
    result = quota.window(conn, quota.REEL, 3600, 20, now)

    # Only 11:30 is inside the last hour.
    assert result["used"] == 1
    assert result["max"] == 20


def test_an_event_exactly_on_the_window_edge_has_aged_out(conn):
    """The window is half-open: an hour old is out, not in."""
    quota.record(conn, quota.REEL, "2026-08-25T10:00:00+00:00")

    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:00:00+00:00")

    assert result["used"] == 0


def test_reset_is_when_the_oldest_event_in_the_window_ages_out(conn):
    quota.record(conn, quota.REEL, "2026-08-25T11:10:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T11:40:00+00:00")

    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")

    # Headroom returns when 11:10 leaves the window, not when 11:40 does.
    assert result["resets_at"] == "2026-08-25T12:10:00+00:00"


def test_an_empty_window_has_nothing_to_reset(conn):
    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")

    assert result == {"used": 0, "max": 20, "resets_at": None}


def test_kinds_do_not_share_a_budget(conn):
    quota.record(conn, "something_else", "2026-08-25T11:40:00+00:00")

    assert quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")["used"] == 0
