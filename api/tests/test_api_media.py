from app.clock import now_iso
from app.services import quota
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
    return ctx


def test_thumb_is_served_after_page_fetch(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    resp = client.get("/api/media/nike-0/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_thumb_404_for_unknown_shortcode(client):
    assert client.get("/api/media/nope/thumb").status_code == 404


def test_full_is_404_until_ready(client, conn, settings, adapter):
    ctx = seed(conn, settings, adapter)
    assert client.get("/api/media/nike-0/full").status_code == 404

    handlers.handle_media_fetch(ctx, {"shortcode": "nike-0"})

    resp = client.get("/api/media/nike-0/full")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")


def test_full_serves_a_named_carousel_child(client, conn, settings, adapter):
    adapter.add_posts("nike", count=1, child_count=2)
    ctx = seed(conn, settings, adapter)
    # seed() only fetched the first page; keep paging until the carousel is indexed
    while conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"] != "":
        handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-10"})

    assert client.get("/api/media/nike-10/full?child=1").status_code == 200
    assert client.get("/api/media/nike-10/full?child=2").status_code == 200
    assert client.get("/api/media/nike-10/full?child=9").status_code == 404


def test_ensure_enqueues_missing_items(client, conn, settings, adapter):
    seed(conn, settings, adapter)

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0", "nike-1"]}
    ).json()

    assert body["statuses"] == {"nike-0": "queued", "nike-1": "queued"}
    assert body["ready"] == 0
    assert body["total"] == 2
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM jobs").fetchall()]
    assert kinds == ["media_fetch", "media_fetch"]


def test_ensure_is_idempotent(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})

    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1


def test_ensure_reports_ready_and_unknown(client, conn, settings, adapter):
    ctx = seed(conn, settings, adapter)
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-0"})

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0", "ghost"]}
    ).json()

    assert body["statuses"] == {"nike-0": "ready", "ghost": "unknown"}
    assert body["ready"] == 1


def test_ensure_leaves_failed_alone_unless_retry(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    conn.execute("UPDATE media_items SET full_status='failed' WHERE shortcode='nike-0'")

    assert client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0"]}
    ).json()["statuses"] == {"nike-0": "failed"}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0"], "retry": True}
    ).json()

    assert body["statuses"] == {"nike-0": "queued"}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1


def test_ensure_refuses_a_reel_when_the_hourly_cap_is_spent(
    client, conn, settings, adapter
):
    """Refuse where the click happens, rather than queueing a job to die."""
    seed(conn, settings, adapter)
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    conn.execute(
        "UPDATE media_items SET kind='reel', full_status='none' WHERE shortcode=?",
        (shortcode,),
    )
    conn.execute("DELETE FROM jobs")
    for _ in range(settings.reel_max_per_hour):
        quota.record(conn, quota.REEL, now_iso())

    body = client.post("/api/media/ensure", json={"shortcodes": [shortcode]}).json()

    assert body["statuses"][shortcode] == "quota"
    assert "cap spent" in body["errors"][shortcode]
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0


def test_ensure_still_queues_a_photo_when_the_reel_cap_is_spent(
    client, conn, settings, adapter
):
    """The reel cap governs scraping, not everything the app does."""
    seed(conn, settings, adapter)
    shortcode = conn.execute(
        "SELECT shortcode FROM media_items WHERE kind!='reel' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE media_items SET full_status='none' WHERE shortcode=?", (shortcode,)
    )
    for _ in range(settings.reel_max_per_hour):
        quota.record(conn, quota.REEL, now_iso())

    body = client.post("/api/media/ensure", json={"shortcodes": [shortcode]}).json()

    assert body["statuses"][shortcode] == "queued"
