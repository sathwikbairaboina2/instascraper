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
