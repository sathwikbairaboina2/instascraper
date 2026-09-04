def _post(client, *urls):
    return client.post("/api/urls", json={"urls": list(urls)})


def test_add_valid_url_queues_fetch(client):
    r = _post(client, "https://www.instagram.com/reel/C8yQvW2xyz/")
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == ["C8yQvW2xyz"]
    assert body["invalid"] == []

    job = client.app_state.runtime  # touch state to prove app is live
    assert job is not None
    rows = client.get("/api/urls").json()["items"]
    assert [i["shortcode"] for i in rows] == ["C8yQvW2xyz"]
    assert rows[0]["status"] == "pending"


def test_add_invalid_url_reported_not_queued(client):
    r = _post(client, "https://example.com/nope", "garbage")
    body = r.json()
    assert body["added"] == []
    assert body["invalid"] == ["https://example.com/nope", "garbage"]
    assert client.get("/api/urls").json()["items"] == []


def test_adding_twice_is_harmless(client):
    _post(client, "https://www.instagram.com/p/C8xPqR9abcd/")
    r = _post(client, "https://www.instagram.com/p/C8xPqR9abcd/")
    assert r.json()["added"] == []
    items = client.get("/api/urls").json()["items"]
    assert len(items) == 1


def test_listed_item_carries_media_once_fetched(client, conn):
    """A direct item whose post has been indexed lists as real media."""
    _post(client, "https://www.instagram.com/p/nike-0/")

    # Simulate the fetch having landed: index the profile's first page the
    # way the worker would, which writes media_items for nike-0.
    from app.ig.fake import FakeAdapter
    from app.worker import handlers
    from app.worker.pacer import Pacer
    from app.worker.runner import HandlerContext

    adapter = client.app_state.runtime.current.adapter
    ctx = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=client.app_state.runtime.current.settings,
        pacer=Pacer(min_interval=0.0),
        cdn_pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    items = client.get("/api/urls").json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["shortcode"] == "nike-0"
    assert item["username"] == "nike"
    assert item["status"] == "indexed"
    assert item["media"]["thumb_url"] == "/api/media/nike-0/thumb"


def test_failed_fetch_surfaces_job_error(client, conn):
    _post(client, "https://www.instagram.com/reel/deadbeef123/")
    conn.execute(
        "UPDATE jobs SET status='failed', error='the reel is no longer available'"
        " WHERE kind='url_fetch'"
    )
    items = client.get("/api/urls").json()["items"]
    assert items[0]["status"] == "failed"
    assert "no longer available" in items[0]["error"]


def test_re_adding_a_failed_url_queues_a_fresh_fetch(client, conn):
    """Pasting the same link again is the retry gesture."""
    _post(client, "https://www.instagram.com/reel/deadbeef123/")
    conn.execute("UPDATE jobs SET status='failed', error='boom' WHERE kind='url_fetch'")

    _post(client, "https://www.instagram.com/reel/deadbeef123/")

    queued = conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE kind='url_fetch' AND status='queued'"
    ).fetchone()["c"]
    assert queued == 1
    assert client.get("/api/urls").json()["items"][0]["status"] == "pending"


def test_remove_forgets_the_url_but_keeps_media(client, conn):
    _post(client, "https://www.instagram.com/p/C8xPqR9abcd/")
    r = client.delete("/api/urls/C8xPqR9abcd")
    assert r.json()["removed"] == 1
    assert client.get("/api/urls").json()["items"] == []
