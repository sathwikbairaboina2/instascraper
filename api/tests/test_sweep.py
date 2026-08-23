from app.worker import queue, sweep


def _seed_profile_and_item(conn, shortcode: str, status: str):
    conn.execute(
        "INSERT OR IGNORE INTO profiles (username, tracked, created_at)"
        " VALUES ('nike', 1, 't')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " full_status, ig_url, discovered_at) VALUES (?,'nike','image','t',0,?,'u','t')",
        (shortcode, status),
    )


def test_sweep_deletes_part_files(conn, settings):
    d = settings.media_dir / "nike" / "A"
    d.mkdir(parents=True)
    (d / "full.jpg.part").write_bytes(b"x")
    (d / "thumb.jpg").write_bytes(b"y")

    result = sweep.sweep(conn, settings.media_dir)

    assert result["parts"] == 1
    assert not (d / "full.jpg.part").exists()
    assert (d / "thumb.jpg").exists()


def test_sweep_resets_interrupted_media_rows(conn, settings):
    _seed_profile_and_item(conn, "A", "fetching")
    _seed_profile_and_item(conn, "B", "queued")
    _seed_profile_and_item(conn, "C", "ready")
    _seed_profile_and_item(conn, "D", "failed")

    result = sweep.sweep(conn, settings.media_dir)

    statuses = dict(
        conn.execute("SELECT shortcode, full_status FROM media_items").fetchall()
    )
    assert result["items"] == 2
    assert statuses == {"A": "none", "B": "none", "C": "ready", "D": "failed"}


def test_sweep_requeues_running_jobs(conn, settings):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)

    result = sweep.sweep(conn, settings.media_dir)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert result["jobs"] == 1
    assert row["status"] == "queued"
    assert row["started_at"] is None


def test_sweep_is_safe_when_media_root_is_missing(conn, tmp_path):
    result = sweep.sweep(conn, tmp_path / "nope")
    assert result == {"parts": 0, "items": 0, "jobs": 0}
