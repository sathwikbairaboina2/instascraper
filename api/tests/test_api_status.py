from app.services import activity
from app.worker import queue


def test_status_reports_clear_breaker_and_zero_depth(client):
    body = client.get("/api/status").json()
    assert body["breaker"]["tripped"] is False
    assert body["queue_depth"] == 0
    assert body["worker"] in {"running", "stopped"}


def test_status_reflects_a_tripped_breaker(client):
    client.app_state.breaker.trip_permanent("Instagram session invalid: checkpoint")
    body = client.get("/api/status").json()
    assert body["breaker"]["tripped"] is True
    assert body["breaker"]["permanent"] is True
    assert "checkpoint" in body["breaker"]["reason"]


def test_status_reports_queue_depth(client, conn):
    queue.enqueue(conn, "page_fetch", {"username": "nike"})
    queue.enqueue(conn, "media_fetch", {"shortcode": "nike-0"})
    assert client.get("/api/status").json()["queue_depth"] == 2


def test_activity_returns_newest_first(client, conn):
    activity.record(conn, "lookup", "nike", None)
    activity.record(conn, "download", "nike", {"count": 3, "base": "x"})

    items = client.get("/api/activity").json()["items"]

    assert [i["action"] for i in items] == ["download", "lookup"]
    assert items[0]["detail"] == {"count": 3, "base": "x"}
    assert items[1]["detail"] is None


def test_activity_respects_limit(client, conn):
    for i in range(5):
        activity.record(conn, "lookup", f"user{i}", None)
    assert len(client.get("/api/activity?limit=2").json()["items"]) == 2


def test_status_reports_the_live_adapter(client):
    body = client.get("/api/status").json()
    assert body["adapter"] == "fake"


def test_app_exposes_a_runtime_holder(client):
    holder = client.app_state.runtime
    assert holder.current.name == "fake"
    assert holder.base is not None


def test_injected_adapter_pins_the_runtime(settings):
    """conftest injects an adapter; it must not be rebuilt from settings."""
    from app.ig.fake import FakeAdapter
    from app.main import create_app

    injected = FakeAdapter()
    app = create_app(settings=settings, adapter=injected, start_worker=False)
    assert app.state.runtime.current.adapter is injected


def test_switching_changes_what_status_reports(client):
    assert client.post("/api/adapter", json={"adapter": "graph"}).status_code == 200
    assert client.get("/api/status").json()["adapter"] == "graph"


def test_switching_is_idempotent(client):
    body = client.post("/api/adapter", json={"adapter": "fake"}).json()
    assert body["adapter"] == "fake"


def test_unknown_adapter_is_rejected(client):
    assert client.post("/api/adapter", json={"adapter": "instaloader"}).status_code == 400


def test_switching_clears_the_breaker(client):
    client.app_state.breaker.trip_permanent("Instagram token invalid: checkpoint")
    assert client.app_state.breaker.state()["tripped"] is True

    client.post("/api/adapter", json={"adapter": "graph"})

    assert client.app_state.breaker.state()["tripped"] is False


def test_switching_persists_the_selection(client, settings):
    from app import runtime

    client.post("/api/adapter", json={"adapter": "graph"})
    assert runtime.read_selection(settings) == "graph"


def test_fake_data_never_reaches_the_graph_root(settings):
    """The isolation the whole feature exists for.

    Built without an injected adapter, so paths are genuinely derived --
    the `client` fixture injects one, which deliberately pins the runtime
    to the base paths and would make this assertion vacuous.
    """
    from dataclasses import replace

    from app import runtime
    from app.main import create_app

    base = replace(settings, adapter="fake", graph_token="", graph_user_id="")
    app = create_app(settings=base, start_worker=False)

    active = app.state.runtime.current.settings
    assert active.db_path == base.db_path.parent / "fake" / base.db_path.name
    assert active.media_dir == base.media_dir.parent / "fake" / base.media_dir.name
    # The export folder is shared on purpose: it holds files the user named.
    assert active.out_dir == base.out_dir

    runtime.prepare_data_root(active)
    assert active.db_path.exists()
    assert not base.db_path.exists(), "fake wrote into the graph root"


def test_status_reports_no_usage_for_an_adapter_that_does_not_track_it(client):
    """The fake adapter never calls Meta; inventing a 0% would read as fact."""
    assert client.get("/api/status").json()["usage"] is None


def test_status_reports_both_reel_windows(client):
    body = client.get("/api/status").json()

    assert body["reel_limits"]["hour"]["max"] == 20
    assert body["reel_limits"]["day"]["max"] == 100
    assert body["reel_limits"]["hour"]["used"] == 0


def test_status_reports_resync_with_next_due(client, conn):
    conn.execute(
        "INSERT INTO profiles (username, tracked, last_synced_at, created_at)"
        " VALUES ('old', 1, '2020-01-01T00:00:00+00:00', 'x'),"
        " ('never', 1, NULL, 'x'), ('loose', 0, NULL, 'x')"
    )
    body = client.get("/api/status").json()["resync"]
    assert body["interval_hours"] == 24.0
    assert body["check_seconds"] == 300.0
    assert body["next_due"] == {"username": "never", "last_synced_at": None}


def test_status_resync_next_due_is_null_when_nothing_is_due(client):
    assert client.get("/api/status").json()["resync"]["next_due"] is None


def test_status_resync_next_due_is_null_when_disabled(client, conn):
    from dataclasses import replace

    conn.execute("INSERT INTO profiles (username, tracked, created_at) VALUES ('a', 1, 'x')")
    holder = client.app_state.runtime
    holder.swap(
        type(holder.current)(
            holder.current.name,
            replace(holder.current.settings, resync_interval_hours=0.0),
            holder.current.adapter,
        )
    )
    body = client.get("/api/status").json()["resync"]
    assert body["interval_hours"] == 0.0
    assert body["next_due"] is None


def test_status_resync_daily_mode_shows_slot_and_zone(client, conn):
    from dataclasses import replace

    conn.execute("INSERT INTO profiles (username, tracked, created_at) VALUES ('a', 1, 'x')")
    holder = client.app_state.runtime
    holder.swap(
        type(holder.current)(
            holder.current.name,
            replace(holder.current.settings, resync_daily_at="06:00", resync_tz="Asia/Kolkata"),
            holder.current.adapter,
        )
    )
    body = client.get("/api/status").json()["resync"]
    assert body["mode"] == "daily"
    assert body["daily_at"] == "06:00" and body["tz"] == "Asia/Kolkata"
    assert body["next_due"]["username"] == "a"
    assert body["slot_next"]
