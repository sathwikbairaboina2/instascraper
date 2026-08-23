import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ctx(settings, conn):
    adapter = FakeAdapter()
    enqueued = []
    context = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: enqueued.append((kind, payload)),
    )
    context.enqueued = enqueued  # type: ignore[attr-defined]
    return context


def test_profile_sync_upserts_row_and_avatar(ctx, settings):
    ctx.adapter.add_profile("nike", post_count=42)

    handlers.handle_profile_sync(ctx, {"username": "nike"})

    row = ctx.conn.execute("SELECT * FROM profiles WHERE username='nike'").fetchone()
    assert row["post_count"] == 42
    assert row["ig_user_id"] == "id-nike"
    assert row["last_synced_at"] is not None
    assert row["avatar_path"] == "nike/avatar.jpg"
    assert (settings.media_dir / "nike" / "avatar.jpg").exists()


def test_profile_sync_enqueues_first_page_only_once(ctx):
    ctx.adapter.add_profile("nike")

    handlers.handle_profile_sync(ctx, {"username": "nike"})
    assert ctx.enqueued == [("page_fetch", {"username": "nike"})]

    ctx.conn.execute("UPDATE profiles SET next_cursor='7' WHERE username='nike'")
    ctx.enqueued.clear()
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    assert ctx.enqueued == []


def test_profile_sync_records_private_profile_then_raises(ctx):
    ctx.adapter.add_profile("secret", is_private=True)

    with pytest.raises(t.IgPrivate):
        handlers.handle_profile_sync(ctx, {"username": "secret"})

    row = ctx.conn.execute("SELECT * FROM profiles WHERE username='secret'").fetchone()
    assert row["is_private"] == 1


def test_profile_sync_propagates_not_found_without_creating_a_row(ctx):
    with pytest.raises(t.IgNotFound):
        handlers.handle_profile_sync(ctx, {"username": "ghost"})
    assert ctx.conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"] == 0


def test_page_fetch_inserts_items_thumbs_and_cursor(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=10)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    items = ctx.conn.execute(
        "SELECT * FROM media_items ORDER BY shortcode"
    ).fetchall()
    assert len(items) == settings.page_size
    assert items[0]["full_status"] == "none"
    thumbs = ctx.conn.execute(
        "SELECT * FROM media_files WHERE role='thumb'"
    ).fetchall()
    assert len(thumbs) == settings.page_size
    assert (settings.media_dir / "nike" / "nike-0" / "thumb.jpg").exists()
    cursor = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"]
    assert cursor == str(settings.page_size)


def test_page_fetch_resumes_from_stored_cursor(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=10)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    shortcodes = [
        r["shortcode"]
        for r in ctx.conn.execute(
            "SELECT shortcode FROM media_items ORDER BY LENGTH(shortcode), shortcode"
        ).fetchall()
    ]
    assert len(shortcodes) == settings.page_size * 2
    assert len(set(shortcodes)) == len(shortcodes)


def test_page_fetch_marks_exhaustion_with_empty_string(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=3)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    cursor = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"]
    assert cursor == ""


def test_page_fetch_on_exhausted_profile_is_a_no_op(ctx):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=2)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    before = len(ctx.adapter.calls)

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    assert len(ctx.adapter.calls) == before, "hit Instagram for an exhausted profile"


def test_page_fetch_upsert_does_not_clobber_ready_media(ctx):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=2)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    ctx.conn.execute("UPDATE media_items SET full_status='ready' WHERE shortcode='nike-0'")
    ctx.conn.execute("UPDATE profiles SET next_cursor=NULL WHERE username='nike'")

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    status = ctx.conn.execute(
        "SELECT full_status FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()["full_status"]
    assert status == "ready"
