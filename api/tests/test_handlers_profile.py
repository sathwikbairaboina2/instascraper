from dataclasses import replace

import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


class CountingPacer:
    """A pacer that records rather than sleeps."""

    def __init__(self):
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


@pytest.fixture
def ctx(settings, conn):
    adapter = FakeAdapter()
    enqueued = []
    context = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=CountingPacer(),
        cdn_pacer=CountingPacer(),
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


def test_profile_sync_restarts_an_exhausted_walk(ctx):
    """Re-sync is the only way back from exhaustion.

    Nothing else clears the empty-string cursor, so a profile indexed under
    a build that ended its walk early would be stuck forever. Business
    Discovery also serves newest first, which makes re-walking from the
    front the only way a post published since the last sync is ever seen.
    """
    ctx.adapter.add_profile("nike")
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    ctx.conn.execute("UPDATE profiles SET next_cursor='' WHERE username='nike'")
    ctx.enqueued.clear()

    handlers.handle_profile_sync(ctx, {"username": "nike"})

    assert ctx.enqueued == [("page_fetch", {"username": "nike"})]
    assert (
        ctx.conn.execute(
            "SELECT next_cursor FROM profiles WHERE username='nike'"
        ).fetchone()["next_cursor"]
        is None
    )


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
    assert len(items) == settings.first_page_size
    assert items[0]["full_status"] == "none"
    thumbs = ctx.conn.execute(
        "SELECT * FROM media_files WHERE role='thumb'"
    ).fetchall()
    assert len(thumbs) == settings.first_page_size
    assert (settings.media_dir / "nike" / "nike-0" / "thumb.jpg").exists()
    cursor = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"]
    assert cursor == str(settings.first_page_size)


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
    assert len(shortcodes) == settings.first_page_size + settings.page_size
    assert len(set(shortcodes)) == len(shortcodes)


def test_page_fetch_marks_exhaustion_with_empty_string(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=1)
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


def test_first_page_is_small_and_load_more_takes_a_full_page(ctx, settings):
    # The first page costs one request per post for thumbnails, and it is
    # spent before the user has said whether this is even the right profile.
    # Keep it cheap; "Load more" is where the appetite is stated.
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=20)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})
    first = ctx.conn.execute("SELECT COUNT(*) c FROM media_items").fetchone()["c"]
    assert first == settings.first_page_size

    handlers.handle_page_fetch(ctx, {"username": "nike"})
    second = ctx.conn.execute("SELECT COUNT(*) c FROM media_items").fetchone()["c"]
    assert second == settings.first_page_size + settings.page_size


def test_page_fetch_persists_media_sources(ctx):
    """The adapter cannot look a post up later, so the urls are stored now."""
    import json

    ctx.adapter.add_profile("nike", post_count=1)
    ctx.adapter.posts["nike"] = [
        t.IgPost(
            shortcode="s1",
            kind="image",
            taken_at_iso="2026-01-01T00:00:00+00:00",
            caption="",
            is_video=False,
            child_count=1,
            thumb_url="https://cdn.test/t.jpg",
            ig_url="https://instagram.com/p/s1/",
            sources=(t.MediaSource(0, "https://cdn.test/full.jpg", "image/jpeg", False),),
        )
    ]
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    row = ctx.conn.execute(
        "SELECT src_urls, src_urls_at FROM media_items WHERE shortcode='s1'"
    ).fetchone()
    stored = json.loads(row["src_urls"])
    assert stored == [
        {
            "child_idx": 0,
            "url": "https://cdn.test/full.jpg",
            "mime": "image/jpeg",
            "is_video": False,
        }
    ]
    assert row["src_urls_at"]


def test_profile_sync_stores_the_follower_count(ctx):
    ctx.adapter.add_profile("nike", post_count=42)
    ctx.adapter.profiles["nike"] = replace(
        ctx.adapter.profiles["nike"], followers_count=1234
    )

    handlers.handle_profile_sync(ctx, {"username": "nike"})

    row = ctx.conn.execute(
        "SELECT followers_count FROM profiles WHERE username='nike'"
    ).fetchone()
    assert row["followers_count"] == 1234


def test_thumbnails_are_paced_separately_from_graph_calls(ctx, settings):
    """CDN downloads do not spend Meta's quota, so they do not wait like it."""
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=5)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    graph_before = ctx.pacer.waits
    cdn_before = ctx.cdn_pacer.waits

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    # One Graph call for the listing, one CDN fetch per thumbnail on it.
    assert ctx.pacer.waits - graph_before == 1
    assert ctx.cdn_pacer.waits - cdn_before == settings.first_page_size


def test_page_fetch_readopts_a_thumbnail_whose_row_went_missing(ctx, settings):
    """A file on disk with no media_files row used to stay invisible forever.

    The old guard skipped the fetch when the file existed, and the insert lived
    inside that same branch, so the row was never written back. The api serves
    the row, not the file, and the tile stayed broken until the whole profile
    cache was cleared.
    """
    ctx.adapter.add_profile("nike", post_count=1)
    ctx.adapter.add_posts("nike", count=1)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    shortcode = ctx.conn.execute(
        "SELECT shortcode FROM media_items WHERE username='nike'"
    ).fetchone()["shortcode"]
    thumb = settings.media_dir / "nike" / shortcode / "thumb.jpg"
    assert thumb.exists()

    # Lose the row, keep the file. This is the state a crash between the write
    # and the insert leaves behind.
    ctx.conn.execute(
        "DELETE FROM media_files WHERE shortcode=? AND role='thumb'", (shortcode,)
    )
    ctx.conn.execute("UPDATE profiles SET next_cursor=NULL WHERE username='nike'")
    before = ctx.cdn_pacer.waits

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    row = ctx.conn.execute(
        "SELECT path, bytes FROM media_files WHERE shortcode=? AND role='thumb'",
        (shortcode,),
    ).fetchone()
    assert row is not None, "the row should have been written back"
    assert row["bytes"] == thumb.stat().st_size
    assert ctx.cdn_pacer.waits == before, "adopting a cached file must not re-fetch it"


def test_page_fetch_still_downloads_when_the_file_is_gone(ctx, settings):
    ctx.adapter.add_profile("nike", post_count=1)
    ctx.adapter.add_posts("nike", count=1)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    shortcode = ctx.conn.execute(
        "SELECT shortcode FROM media_items WHERE username='nike'"
    ).fetchone()["shortcode"]
    thumb = settings.media_dir / "nike" / shortcode / "thumb.jpg"
    thumb.unlink()
    ctx.conn.execute(
        "DELETE FROM media_files WHERE shortcode=? AND role='thumb'", (shortcode,)
    )
    ctx.conn.execute("UPDATE profiles SET next_cursor=NULL WHERE username='nike'")

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    assert thumb.exists()
    assert ctx.conn.execute(
        "SELECT 1 FROM media_files WHERE shortcode=? AND role='thumb'", (shortcode,)
    ).fetchone() is not None




