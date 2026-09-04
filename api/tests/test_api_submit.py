import json

from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


class FakePublisher:
    def __init__(self, configured=True):
        self.configured = configured
        self.published: list[dict] = []

    def publish(self, envelope):
        if not self.configured:
            raise RuntimeError("not configured")
        self.published.append(envelope)


def _prepared(client, conn, settings, adapter):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), cdn_pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    handlers.handle_media_fetch(ctx, {"shortcode": shortcode})
    client.post("/api/recreate", json={"shortcodes": [shortcode]})
    client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": None})
    return shortcode


def test_submit_publishes_and_marks_submitted(client, conn, settings, adapter):
    shortcode = _prepared(client, conn, settings, adapter)
    publisher = FakePublisher()
    client.app_state.publisher = publisher

    r = client.post(f"/api/recreate/{shortcode}/submit")

    assert r.status_code == 200
    assert r.json()["status"] == "submitted"
    assert publisher.published[0]["source_ref"] == shortcode
    row = conn.execute(
        "SELECT status FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    assert row["status"] == "submitted"


def test_submit_requires_a_prepared_item(client, conn, settings, adapter):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), cdn_pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    client.post("/api/recreate", json={"shortcodes": [shortcode]})
    client.app_state.publisher = FakePublisher()

    r = client.post(f"/api/recreate/{shortcode}/submit")

    assert r.status_code == 409


def test_submit_unknown_shortcode_is_404(client):
    client.app_state.publisher = FakePublisher()
    assert client.post("/api/recreate/nope/submit").status_code == 404


def test_submit_without_queue_config_is_503(client, conn, settings, adapter):
    shortcode = _prepared(client, conn, settings, adapter)
    client.app_state.publisher = FakePublisher(configured=False)

    r = client.post(f"/api/recreate/{shortcode}/submit")

    assert r.status_code == 503
    row = conn.execute(
        "SELECT status FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    assert row["status"] == "prepared"


def test_submitting_twice_publishes_twice_but_stays_submitted(client, conn, settings, adapter):
    """A resend is deliberate; instacreator dedupes on source_ref anyway."""
    shortcode = _prepared(client, conn, settings, adapter)
    publisher = FakePublisher()
    client.app_state.publisher = publisher

    client.post(f"/api/recreate/{shortcode}/submit")
    r = client.post(f"/api/recreate/{shortcode}/submit")

    assert r.status_code == 200
    assert len(publisher.published) == 2
