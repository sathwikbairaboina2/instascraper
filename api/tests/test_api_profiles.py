import json

from app.worker import handlers, queue
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def seed(client, conn, settings, adapter, username="nike"):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), cdn_pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": username})
    handlers.handle_page_fetch(ctx, {"username": username})


def test_sync_enqueues_a_job_and_logs_the_lookup(client, conn):
    body = client.post("/api/profiles/nike/sync").json()
    assert body["queued"] is True

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["kind"] == "profile_sync"
    assert json.loads(row["payload"]) == {"username": "nike"}
    assert conn.execute(
        "SELECT action FROM activity_log"
    ).fetchone()["action"] == "lookup"


def test_sync_is_idempotent_while_queued(client):
    assert client.post("/api/profiles/nike/sync").json()["queued"] is True
    assert client.post("/api/profiles/nike/sync").json()["queued"] is False


def test_get_unknown_profile_is_404_with_last_error(client, conn):
    queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    job_id = queue.claim_next(conn)["id"]
    queue.fail(conn, job_id, "ghost does not exist", retryable=False)

    resp = client.get("/api/profiles/ghost")

    assert resp.status_code == 404
    assert "does not exist" in resp.json()["detail"]["last_error"]


def test_get_profile_returns_detail(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.get("/api/profiles/nike").json()

    assert body["username"] == "nike"
    assert body["post_count"] == 10
    assert body["avatar_url"] == "/api/profiles/nike/avatar"
    assert body["exhausted"] is False
    assert body["cached_count"] == 0


def test_media_page_returns_thumb_urls_and_total(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.get("/api/profiles/nike/media?limit=2&offset=0").json()

    assert body["total"] == settings.first_page_size
    assert len(body["items"]) == 2
    assert body["items"][0]["thumb_url"].startswith("/api/media/")
    assert body["items"][0]["full_status"] == "none"
    assert body["exhausted"] is False


def test_media_page_is_newest_first(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    items = client.get("/api/profiles/nike/media?limit=50").json()["items"]
    taken = [i["taken_at"] for i in items]
    assert taken == sorted(taken, reverse=True)


def test_tracked_toggle_round_trips(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    assert client.put("/api/profiles/nike/tracked", json={"tracked": True}).json() == {
        "tracked": True
    }
    assert [p["username"] for p in client.get("/api/profiles").json()["items"]] == ["nike"]

    client.put("/api/profiles/nike/tracked", json={"tracked": False})
    assert client.get("/api/profiles").json()["items"] == []


def test_load_more_enqueues_page_fetch(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.post("/api/profiles/nike/load-more").json()

    assert body == {"queued": True, "exhausted": False}
    assert conn.execute(
        "SELECT kind FROM jobs ORDER BY id DESC"
    ).fetchone()["kind"] == "page_fetch"


def test_load_more_on_exhausted_profile_queues_nothing(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    conn.execute("UPDATE profiles SET next_cursor='' WHERE username='nike'")

    body = client.post("/api/profiles/nike/load-more").json()

    assert body == {"queued": False, "exhausted": True}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0


def test_clear_cache_removes_files_and_resets_status(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    conn.execute("UPDATE media_items SET full_status='ready'")

    body = client.delete("/api/profiles/nike/cache").json()

    assert body["removed_files"] > 0
    assert not (settings.media_dir / "nike").exists()
    statuses = {
        r["full_status"] for r in conn.execute("SELECT full_status FROM media_items")
    }
    assert statuses == {"none"}
    assert conn.execute("SELECT COUNT(*) c FROM media_files").fetchone()["c"] == 0


def test_profile_detail_reports_the_follower_count(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    conn.execute("UPDATE profiles SET followers_count=99 WHERE username='nike'")

    body = client.get("/api/profiles/nike").json()

    assert body["followers_count"] == 99


def test_media_summary_names_which_carousel_children_are_video(
    client, conn, settings, adapter
):
    """A carousel is not a video, but a slide inside it can be.

    The lightbox picked <video> or <img> from the post-level flag, so a video
    slide in a carousel rendered as a broken image.
    """
    seed(client, conn, settings, adapter)
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    conn.execute(
        "UPDATE media_items SET child_count=3, src_urls=? WHERE shortcode=?",
        (
            json.dumps(
                [
                    {"child_idx": 1, "url": "https://cdn/a.jpg", "mime": "image/jpeg", "is_video": False},
                    {"child_idx": 2, "url": "https://cdn/b.mp4", "mime": "video/mp4", "is_video": True},
                    {"child_idx": 3, "url": "https://cdn/c.jpg", "mime": "image/jpeg", "is_video": False},
                ]
            ),
            shortcode,
        ),
    )

    items = client.get("/api/profiles/nike/media").json()["items"]
    item = next(i for i in items if i["shortcode"] == shortcode)

    assert item["video_children"] == [2]


def test_media_summary_carries_engagement(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    conn.execute(
        "UPDATE media_items SET like_count=101, comments_count=7, view_count=NULL"
        " WHERE shortcode=?",
        (shortcode,),
    )

    items = client.get("/api/profiles/nike/media").json()["items"]
    item = next(i for i in items if i["shortcode"] == shortcode)

    assert item["like_count"] == 101
    assert item["comments_count"] == 7
    assert item["view_count"] is None


def test_a_deduped_sync_does_not_log_a_second_lookup(client, conn):
    """Two rapid asks are one fetch, so they are one lookup line."""
    first = client.post("/api/profiles/nike/sync").json()
    second = client.post("/api/profiles/nike/sync").json()

    assert first["queued"] is True
    assert second["queued"] is False, "the second ask should have been deduped"

    rows = conn.execute(
        "SELECT COUNT(*) c FROM activity_log WHERE action='lookup' AND target='nike'"
    ).fetchone()["c"]
    assert rows == 1
