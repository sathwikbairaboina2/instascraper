import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ctx(settings, conn):
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=1)
    adapter.add_posts("nike", count=1, video=True)
    return HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        cdn_pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: None,
    )


def _payload(shortcode):
    return {"shortcode": shortcode, "url": f"https://www.instagram.com/p/{shortcode}/"}


def test_url_fetch_lands_media_without_a_synced_profile(ctx, settings):
    """The owner has never been looked up; the fetch must not require it."""
    handlers.handle_url_fetch(ctx, _payload("nike-1"))

    item = ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode='nike-1'"
    ).fetchone()
    assert item is not None
    assert item["username"] == "nike"
    assert item["full_status"] == "ready"

    full = ctx.conn.execute(
        "SELECT * FROM media_files WHERE shortcode='nike-1' AND role='full'"
    ).fetchall()
    assert len(full) == 1
    assert (settings.media_dir / full[0]["path"]).exists()

    thumb = ctx.conn.execute(
        "SELECT * FROM media_files WHERE shortcode='nike-1' AND role='thumb'"
    ).fetchone()
    assert thumb is not None
    assert (settings.media_dir / thumb["path"]).exists()


def test_url_fetch_creates_a_stub_profile_row(ctx):
    """media_items.username has a FK; the owner gets a row, untracked."""
    handlers.handle_url_fetch(ctx, _payload("nike-1"))

    profile = ctx.conn.execute(
        "SELECT * FROM profiles WHERE username='nike'"
    ).fetchone()
    assert profile is not None
    assert profile["tracked"] == 0


def test_url_fetch_keeps_an_existing_profile_row(ctx):
    ctx.conn.execute(
        "INSERT INTO profiles (username, full_name, tracked, created_at)"
        " VALUES ('nike', 'Nike', 1, '2026-01-01T00:00:00+00:00')"
    )
    handlers.handle_url_fetch(ctx, _payload("nike-1"))

    profile = ctx.conn.execute(
        "SELECT * FROM profiles WHERE username='nike'"
    ).fetchone()
    assert profile["tracked"] == 1
    assert profile["full_name"] == "Nike"


def test_url_fetch_is_a_no_op_when_already_ready(ctx):
    handlers.handle_url_fetch(ctx, _payload("nike-1"))
    before = len(ctx.adapter.calls)

    handlers.handle_url_fetch(ctx, _payload("nike-1"))

    assert len(ctx.adapter.calls) == before


def test_url_fetch_propagates_terminal_errors(ctx):
    with pytest.raises(t.IgNotFound):
        handlers.handle_url_fetch(ctx, _payload("does-not-exist"))


@pytest.fixture
def indexed_ctx(settings, conn):
    """A profile already walked: its posts are indexed with src_urls."""
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=1, child_count=3)
    ctx = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        cdn_pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    return ctx


def test_an_already_indexed_post_goes_through_the_graph_path(indexed_ctx):
    """An image carousel a profile walk indexed is downloadable from the CDN;
    sending it through yt-dlp would fail with "no video" for nothing."""
    handlers.handle_url_fetch(indexed_ctx, _payload("nike-0"))

    item = indexed_ctx.conn.execute(
        "SELECT full_status FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()
    assert item["full_status"] == "ready"
    assert not any(c.method == "fetch_url" for c in indexed_ctx.adapter.calls)
    assert any(c.method == "fetch_media" for c in indexed_ctx.adapter.calls)


def test_a_failed_indexed_fetch_marks_the_row(indexed_ctx):
    indexed_ctx.adapter.raise_on("fetch_media", t.IgTransient("reset"))

    with pytest.raises(t.IgTransient):
        handlers.handle_url_fetch(indexed_ctx, _payload("nike-0"))

    item = indexed_ctx.conn.execute(
        "SELECT full_status, full_error FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()
    assert item["full_status"] == "failed"
    assert "reset" in item["full_error"]
