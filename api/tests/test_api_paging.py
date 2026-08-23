"""P9: the grid must be able to reach every indexed post.

The UI requested a fixed limit=120/offset=0 while "Load more" kept indexing
36 more at a time, so anything past the newest 120 was invisible even though
the API held it.
"""
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def _ctx(conn, settings, adapter):
    return HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )


def index_many(conn, settings, adapter, count):
    adapter.add_posts("nike", count=count)
    ctx = _ctx(conn, settings, adapter)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    while conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"] != "":
        handlers.handle_page_fetch(ctx, {"username": "nike"})
    return ctx


def test_total_reports_everything_indexed(client, conn, settings, adapter):
    index_many(conn, settings, adapter, 130)
    body = client.get("/api/profiles/nike/media?limit=10").json()
    assert body["total"] == 140  # 10 from the adapter fixture + 130 added
    assert len(body["items"]) == 10


def test_offset_reaches_past_the_first_window(client, conn, settings, adapter):
    index_many(conn, settings, adapter, 130)

    first = client.get("/api/profiles/nike/media?limit=120&offset=0").json()
    second = client.get("/api/profiles/nike/media?limit=120&offset=120").json()

    assert len(first["items"]) == 120
    assert len(second["items"]) == 20
    overlap = {i["shortcode"] for i in first["items"]} & {
        i["shortcode"] for i in second["items"]
    }
    assert overlap == set(), "pages must not repeat items"


def test_limit_accepts_a_window_large_enough_for_every_post(client, conn, settings, adapter):
    index_many(conn, settings, adapter, 130)
    body = client.get("/api/profiles/nike/media?limit=500&offset=0").json()
    assert len(body["items"]) == 140 == body["total"]


def test_paging_is_stable_across_requests(client, conn, settings, adapter):
    """Ordering must be deterministic or a growing window would shuffle."""
    index_many(conn, settings, adapter, 40)
    a = [i["shortcode"] for i in client.get("/api/profiles/nike/media?limit=50").json()["items"]]
    b = [i["shortcode"] for i in client.get("/api/profiles/nike/media?limit=50").json()["items"]]
    assert a == b
