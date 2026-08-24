import json

from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def seed(conn, settings, adapter):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), cdn_pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    return conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]


def test_marking_a_post_snapshots_what_it_needs(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)

    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    row = conn.execute(
        "SELECT * FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    assert row["username"] == "nike"
    assert row["ig_url"]
    assert row["status"] == "selected"


def test_marking_twice_does_not_duplicate_or_reset(client, conn, settings, adapter):
    """Sending a whole selection twice is a normal accident, not a reset."""
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})
    conn.execute(
        "UPDATE recreate_items SET status='submitted' WHERE shortcode=?", (shortcode,)
    )

    body = client.post("/api/recreate", json={"shortcodes": [shortcode]}).json()

    assert body["added"] == 0
    rows = conn.execute("SELECT status FROM recreate_items").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "submitted"


def test_an_item_outlives_the_post_it_came_from(client, conn, settings, adapter):
    """The list is queued work, not a view of the cache.

    Clearing a profile, or its rows going away, must not silently delete
    something already lined up for the generator.
    """
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    conn.execute("DELETE FROM media_items WHERE shortcode=?", (shortcode,))

    items = client.get("/api/recreate").json()["items"]
    assert [i["shortcode"] for i in items] == [shortcode]
    assert items[0]["ig_url"]


def test_marking_an_unknown_post_is_reported_not_invented(client, conn):
    body = client.post("/api/recreate", json={"shortcodes": ["nope"]}).json()

    assert body["added"] == 0
    assert "nope" in body["unknown"]


def test_an_item_can_be_removed(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    client.delete(f"/api/recreate/{shortcode}")

    assert client.get("/api/recreate").json()["items"] == []


def test_one_item_can_be_read_for_its_own_page(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    body = client.get(f"/api/recreate/{shortcode}").json()

    assert body["shortcode"] == shortcode
    assert body["status"] == "selected"


def test_reading_an_item_that_was_never_marked_is_a_404(client):
    assert client.get("/api/recreate/nope").status_code == 404
