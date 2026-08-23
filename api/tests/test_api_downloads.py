import json

import pytest

from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def _ctx(conn, settings, adapter):
    return HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )


def _drain_pages(ctx, conn):
    while conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"] != "":
        handlers.handle_page_fetch(ctx, {"username": "nike"})


@pytest.fixture
def ready(conn, settings, adapter):
    ctx = _ctx(conn, settings, adapter)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    _drain_pages(ctx, conn)
    for shortcode in ("nike-0", "nike-1", "nike-2"):
        handlers.handle_media_fetch(ctx, {"shortcode": shortcode})
    return ctx


def test_download_writes_numbered_files_oldest_first(client, ready, settings):
    body = client.post(
        "/api/downloads",
        json={"shortcodes": ["nike-2", "nike-0", "nike-1"], "base": "trip"},
    ).json()

    assert body["count"] == 3
    written = sorted(p.name for p in settings.out_dir.iterdir())
    assert written == ["trip_01.jpg", "trip_02.jpg", "trip_03.jpg"]
    # the fake writes real PNG bytes so a fake-adapter stack renders in a browser
    assert (settings.out_dir / "trip_01.jpg").read_bytes()[1:4] == b"PNG"


def test_download_names_carousel_children_with_letters(client, conn, settings, adapter):
    adapter.add_posts("nike", count=1, child_count=3)
    ctx = _ctx(conn, settings, adapter)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    _drain_pages(ctx, conn)
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-10"})

    client.post("/api/downloads", json={"shortcodes": ["nike-10"], "base": "set"})

    assert sorted(p.name for p in settings.out_dir.iterdir()) == [
        "set_01a.jpg", "set_01b.jpg", "set_01c.jpg",
    ]


def test_download_sanitizes_the_base_filename(client, ready, settings):
    client.post(
        "/api/downloads", json={"shortcodes": ["nike-0"], "base": "../../escape"}
    )
    written = [p.name for p in settings.out_dir.iterdir()]
    assert written == ["escape_01.jpg"]
    assert not (settings.out_dir.parent / "escape_01.jpg").exists()


def test_download_never_overwrites_an_existing_file(client, ready, settings):
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})

    assert sorted(p.name for p in settings.out_dir.iterdir()) == [
        "trip_01-1.jpg", "trip_01.jpg",
    ]


def test_download_409s_when_something_is_not_ready(client, ready, conn, settings):
    conn.execute("UPDATE media_items SET full_status='none' WHERE shortcode='nike-1'")

    resp = client.post(
        "/api/downloads", json={"shortcodes": ["nike-0", "nike-1"], "base": "trip"}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["not_ready"] == ["nike-1"]
    assert list(settings.out_dir.iterdir()) == []


def test_download_400s_on_empty_selection(client, ready):
    assert client.post(
        "/api/downloads", json={"shortcodes": [], "base": "trip"}
    ).status_code == 400


def test_download_writes_one_activity_row(client, ready, conn):
    client.post(
        "/api/downloads", json={"shortcodes": ["nike-0", "nike-1"], "base": "trip"}
    )

    rows = conn.execute(
        "SELECT * FROM activity_log WHERE action='download'"
    ).fetchall()
    assert len(rows) == 1

    detail = json.loads(rows[0]["detail"])
    assert detail["count"] == 2
    assert detail["base"] == "trip"
    assert detail["shortcodes"] == ["nike-0", "nike-1"]


def test_download_leaves_no_part_files(client, ready, settings):
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})
    assert list(settings.out_dir.glob("*.part")) == []
