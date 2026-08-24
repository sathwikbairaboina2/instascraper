from app import db


def test_wal_and_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_all_five_tables_exist(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"profiles", "media_items", "media_files", "jobs", "activity_log"} <= names


def test_init_schema_is_idempotent(conn, settings):
    db.init_schema(conn)
    db.init_schema(conn)
    assert conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"] == 0


def test_media_files_cascade_on_item_delete(conn):
    conn.execute(
        "INSERT INTO profiles (username, tracked, created_at) VALUES ('a', 0, 'x')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at) VALUES ('S1','a','image','t',0,'u','t')"
    )
    conn.execute(
        "INSERT INTO media_files (shortcode, role, child_idx, path)"
        " VALUES ('S1','full',0,'p')"
    )
    conn.execute("DELETE FROM media_items WHERE shortcode='S1'")
    assert conn.execute("SELECT COUNT(*) c FROM media_files").fetchone()["c"] == 0


def test_migrate_adds_src_url_columns_to_an_old_database(settings):
    conn = db.new_conn(settings)
    conn.execute(
        "CREATE TABLE media_items ("
        " shortcode TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,"
        " taken_at TEXT NOT NULL, caption TEXT, is_video INTEGER NOT NULL,"
        " child_count INTEGER NOT NULL DEFAULT 1, full_status TEXT NOT NULL DEFAULT 'none',"
        " full_error TEXT, ig_url TEXT NOT NULL, discovered_at TEXT NOT NULL)"
    )

    db.migrate(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(media_items)")}
    assert "src_urls" in columns
    assert "src_urls_at" in columns
    conn.close()


def test_migrate_is_idempotent(conn):
    db.migrate(conn)
    db.migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(media_items)")}
    assert "src_urls" in columns
