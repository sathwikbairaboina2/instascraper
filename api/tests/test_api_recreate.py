import json

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
    return conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]


def test_marking_a_post_snapshots_what_it_needs(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)

    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    row = conn.execute(
        "SELECT * FROM recreate_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    assert row["username"] == "nike"
    assert row["ig_url"]
    assert row["status"] == "selected"


def test_marking_twice_does_not_duplicate_or_reset(client, conn, settings, adapter):
    """Sending a whole selection twice is a normal accident, not a reset."""
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})
    conn.execute(
        "UPDATE recreate_items SET status='submitted' WHERE shortcode=?", (shortcode,)
    )

    body = client.post("/api/recreate", json={"shortcodes": [shortcode]}).json()

    assert body["added"] == 0
    rows = conn.execute("SELECT status FROM recreate_items").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "submitted"


def test_an_item_outlives_the_post_it_came_from(client, conn, settings, adapter):
    """The list is queued work, not a view of the cache.

    Clearing a profile, or its rows going away, must not silently delete
    something already lined up for the generator.
    """
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    conn.execute("DELETE FROM media_items WHERE shortcode=?", (shortcode,))

    items = client.get("/api/recreate").json()["items"]
    assert [i["shortcode"] for i in items] == [shortcode]
    assert items[0]["ig_url"]


def test_marking_an_unknown_post_is_reported_not_invented(client, conn):
    body = client.post("/api/recreate", json={"shortcodes": ["nope"]}).json()

    assert body["added"] == 0
    assert "nope" in body["unknown"]


def test_an_item_can_be_removed(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    client.delete(f"/api/recreate/{shortcode}")

    assert client.get("/api/recreate").json()["items"] == []


def test_one_item_can_be_read_for_its_own_page(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    body = client.get(f"/api/recreate/{shortcode}").json()

    assert body["shortcode"] == shortcode
    assert body["status"] == "selected"


def test_reading_an_item_that_was_never_marked_is_a_404(client):
    assert client.get("/api/recreate/nope").status_code == 404


def ready_carousel(conn, shortcode, children=3):
    """A downloaded carousel: media rows plus the files that prove it."""
    conn.execute(
        "UPDATE media_items SET kind='carousel', child_count=?, full_status='ready'"
        " WHERE shortcode=?",
        (children, shortcode),
    )
    for idx in range(1, children + 1):
        conn.execute(
            "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
            " width, height) VALUES (?,'full',?,?,?,?,?,?)"
            " ON CONFLICT(shortcode, role, child_idx) DO UPDATE SET path=excluded.path",
            (shortcode, idx, f"nike/{shortcode}/full_{idx}.jpg", "image/jpeg", 100 + idx, 1080, 1350),
        )


def test_preparing_builds_a_payload_naming_every_chosen_slide(
    client, conn, settings, adapter
):
    shortcode = seed(conn, settings, adapter)
    ready_carousel(conn, shortcode)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    body = client.post(
        f"/api/recreate/{shortcode}/prepare", json={"slides": [1, 3]}
    ).json()

    assert body["shortcode"] == shortcode
    assert [s["index"] for s in body["slides"]] == [1, 3]
    assert body["slides"][0]["path"] == f"nike/{shortcode}/full_1.jpg"
    assert body["slides"][0]["bytes"] == 101


def test_a_prepared_item_is_prepared_not_submitted(client, conn, settings, adapter):
    """Nothing has been handed to the creator yet, so it cannot say so."""
    shortcode = seed(conn, settings, adapter)
    ready_carousel(conn, shortcode)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": [1]})

    row = conn.execute(
        "SELECT status, payload, prepared_at FROM recreate_items WHERE shortcode=?",
        (shortcode,),
    ).fetchone()
    assert row["status"] == "prepared"
    assert row["prepared_at"]
    assert json.loads(row["payload"])["shortcode"] == shortcode


def test_the_payload_survives_a_reload(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    ready_carousel(conn, shortcode)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})
    client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": [2]})

    item = client.get(f"/api/recreate/{shortcode}").json()

    assert [s["index"] for s in item["payload"]["slides"]] == [2]


def test_preparing_without_the_files_is_refused(client, conn, settings, adapter):
    """A payload naming files that are not there is worse than no payload."""
    shortcode = seed(conn, settings, adapter)
    conn.execute(
        "UPDATE media_items SET full_status='none' WHERE shortcode=?", (shortcode,)
    )
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    res = client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": None})

    assert res.status_code == 409
    assert "not downloaded" in res.json()["detail"]["message"]


def test_asking_for_a_slide_that_does_not_exist_is_refused(
    client, conn, settings, adapter
):
    shortcode = seed(conn, settings, adapter)
    ready_carousel(conn, shortcode, children=2)
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    res = client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": [1, 9]})

    assert res.status_code == 400
    assert "9" in res.json()["detail"]["message"]


def test_a_single_post_needs_no_slide_choice(client, conn, settings, adapter):
    shortcode = seed(conn, settings, adapter)
    conn.execute(
        "UPDATE media_items SET kind='image', child_count=1, full_status='ready'"
        " WHERE shortcode=?",
        (shortcode,),
    )
    conn.execute(
        "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
        " width, height) VALUES (?,'full',0,?,?,?,?,?)",
        (shortcode, f"nike/{shortcode}/full.jpg", "image/jpeg", 900, 1080, 1080),
    )
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    body = client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": None}).json()

    assert [s["index"] for s in body["slides"]] == [0]


def test_preparing_something_never_marked_is_a_404(client):
    assert client.post("/api/recreate/nope/prepare", json={"slides": None}).status_code == 404


def test_preparing_reads_dimensions_a_row_never_learned(
    client, conn, settings, adapter
):
    """Rows written before the probe existed shipped `"width": null` forever.

    The probe was never the problem -- nothing re-read a file already on disk.
    """
    shortcode = seed(conn, settings, adapter)
    conn.execute(
        "UPDATE media_items SET full_status='ready' WHERE shortcode=?", (shortcode,)
    )

    # A real JPEG on disk, and a row that does not know how big it is.
    dest = settings.media_dir / "nike" / shortcode / "full.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_jpeg(width=800, height=600))
    conn.execute(
        "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
        " width, height) VALUES (?,'full',0,?,?,?,NULL,NULL)",
        (shortcode, f"nike/{shortcode}/full.jpg", "image/jpeg", dest.stat().st_size),
    )
    client.post("/api/recreate", json={"shortcodes": [shortcode]})

    body = client.post(f"/api/recreate/{shortcode}/prepare", json={"slides": None}).json()

    assert body["slides"][0]["width"] == 800
    assert body["slides"][0]["height"] == 600

    stored = conn.execute(
        "SELECT width, height FROM media_files WHERE shortcode=? AND role='full'",
        (shortcode,),
    ).fetchone()
    assert (stored["width"], stored["height"]) == (800, 600), "and remembered"


def _jpeg(width: int, height: int) -> bytes:
    """The smallest thing app.probe will read a size out of."""
    import struct

    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xd9"
    )
