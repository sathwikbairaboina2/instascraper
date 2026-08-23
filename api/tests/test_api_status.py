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
