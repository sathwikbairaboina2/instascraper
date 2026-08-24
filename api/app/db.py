import sqlite3
import threading
from pathlib import Path

from app.config import Settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_local = threading.local()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is required for request-scoped connections:
    # FastAPI resolves a sync dependency and runs the sync endpoint on
    # different AnyIO threadpool threads, so the connection legitimately
    # moves between threads. It is still owned by exactly one request at a
    # time, so there is no concurrent use of a single connection.
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def new_conn(settings: Settings) -> sqlite3.Connection:
    """A fresh connection owned by one request. The caller must close it."""
    return _connect(settings.db_path)


def get_conn(settings: Settings) -> sqlite3.Connection:
    """Long-lived connection cached per thread. Used by the worker thread."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect(settings.db_path)
        _local.conn = conn
    return conn


def reset_thread_state() -> None:
    """Test helper: forget this thread's cached connection."""
    if getattr(_local, "conn", None) is not None:
        _local.conn = None


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())


# SQLite has no ADD COLUMN IF NOT EXISTS, and schema.sql only ever creates
# tables that do not already exist. Columns added to an existing table
# therefore need this. Keyed by table, then by column.
_ADDED_COLUMNS = {
    "media_items": {
        "src_urls": "ALTER TABLE media_items ADD COLUMN src_urls TEXT",
        "src_urls_at": "ALTER TABLE media_items ADD COLUMN src_urls_at TEXT",
    },
}


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema. Idempotent."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table does not exist yet; schema.sql just created it
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(ddl)
