import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ready_ctx(settings, conn):
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=2)
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
    # Two pages: the first one is deliberately small.
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    return ctx


def test_media_fetch_writes_single_file_and_marks_ready(ready_ctx, settings):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})

    item = ready_ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()
    files = ready_ctx.conn.execute(
        "SELECT * FROM media_files WHERE shortcode='nike-0' AND role='full'"
    ).fetchall()
    assert item["full_status"] == "ready"
    assert len(files) == 1
    assert files[0]["child_idx"] == 0
    assert files[0]["path"] == "nike/nike-0/full.jpg"
    assert (settings.media_dir / "nike" / "nike-0" / "full.jpg").exists()


def test_media_fetch_writes_all_carousel_children(ready_ctx):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-2"})

    files = ready_ctx.conn.execute(
        "SELECT child_idx, path FROM media_files"
        " WHERE shortcode='nike-2' AND role='full' ORDER BY child_idx"
    ).fetchall()
    assert [f["child_idx"] for f in files] == [1, 2, 3]
    assert files[0]["path"] == "nike/nike-2/full_1.jpg"


def test_media_fetch_is_a_no_op_when_already_ready(ready_ctx):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})
    before = len(ready_ctx.adapter.calls)

    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})

    assert len(ready_ctx.adapter.calls) == before


def test_media_fetch_marks_failed_and_reraises(ready_ctx, settings):
    ready_ctx.adapter.raise_on("fetch_media", t.IgTransient("reset"))

    with pytest.raises(t.IgTransient):
        handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-1"})

    item = ready_ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode='nike-1'"
    ).fetchone()
    assert item["full_status"] == "failed"
    assert "reset" in item["full_error"]
    assert list(settings.media_dir.rglob("*.part")) == []


def test_media_fetch_unknown_shortcode_raises_not_found(ready_ctx):
    with pytest.raises(t.IgNotFound):
        handlers.handle_media_fetch(ready_ctx, {"shortcode": "nope"})


def test_handlers_registry_covers_every_job_kind():
    from app.worker import queue

    assert set(handlers.HANDLERS) == set(queue.PRIORITY)


class Recording:
    """Captures the hint the handler passes, and writes nothing."""

    def __init__(self):
        self.hint = "unset"

    def fetch_media(self, shortcode, dest_dir, hint=None):
        self.hint = hint
        return []


def recording_ctx(settings, conn, adapter):
    return HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        cdn_pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: None,
    )


def test_media_fetch_hands_the_adapter_a_hint(settings, conn):
    import json

    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike','2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at, src_urls, src_urls_at)"
        " VALUES ('s1','nike','image','2026-01-01T00:00:00+00:00',0,"
        " 'https://instagram.com/p/s1/','2026-01-01T00:00:00+00:00',?,?)",
        (
            json.dumps(
                [
                    {
                        "child_idx": 0,
                        "url": "https://cdn/f.jpg",
                        "mime": "image/jpeg",
                        "is_video": False,
                    }
                ]
            ),
            "2026-01-01T00:00:00+00:00",
        ),
    )

    adapter = Recording()
    handlers.handle_media_fetch(recording_ctx(settings, conn, adapter), {"shortcode": "s1"})

    assert adapter.hint.username == "nike"
    assert adapter.hint.sources == (
        t.MediaSource(0, "https://cdn/f.jpg", "image/jpeg", False),
    )


def test_media_fetch_hint_is_empty_when_nothing_was_stored(settings, conn):
    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike','2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at) VALUES ('s2','nike','image','2026-01-01T00:00:00+00:00',0,"
        " 'https://instagram.com/p/s2/','2026-01-01T00:00:00+00:00')"
    )

    adapter = Recording()
    handlers.handle_media_fetch(recording_ctx(settings, conn, adapter), {"shortcode": "s2"})

    assert adapter.hint.sources == ()
    assert adapter.hint.username == "nike"
