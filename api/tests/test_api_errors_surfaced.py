"""P7: a failed item must say why, in the payload the UI already reads."""
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


def _fail(conn, shortcode, message):
    conn.execute(
        "UPDATE media_items SET full_status='failed', full_error=? WHERE shortcode=?",
        (message, shortcode),
    )


def test_media_list_exposes_full_error(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    _fail(conn, "nike-0", "connection reset by peer")

    items = client.get("/api/profiles/nike/media?limit=50").json()["items"]
    by_code = {i["shortcode"]: i for i in items}

    assert by_code["nike-0"]["full_status"] == "failed"
    assert by_code["nike-0"]["full_error"] == "connection reset by peer"


def test_media_list_error_is_null_when_healthy(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    items = client.get("/api/profiles/nike/media?limit=50").json()["items"]
    assert all(i["full_error"] is None for i in items)


def test_ensure_returns_an_errors_map(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    _fail(conn, "nike-0", "429 rate limited")

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0", "nike-1"]}
    ).json()

    assert body["statuses"]["nike-0"] == "failed"
    assert body["errors"] == {"nike-0": "429 rate limited"}


def test_ensure_errors_map_is_empty_when_nothing_failed(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    body = client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]}).json()
    assert body["errors"] == {}


def test_ensure_retry_clears_the_error_and_requeues(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    _fail(conn, "nike-0", "connection reset by peer")

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0"], "retry": True}
    ).json()

    assert body["statuses"] == {"nike-0": "queued"}
    assert body["errors"] == {}
    row = conn.execute(
        "SELECT full_status, full_error FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()
    assert row["full_status"] == "queued"
    assert row["full_error"] is None
