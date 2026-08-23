import sqlite3
import threading
from pathlib import Path

from app.config import Settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_local = threading.local()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_conn(settings: Settings) -> sqlite3.Connection:
    """One connection per thread. Never share a connection across threads."""
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
