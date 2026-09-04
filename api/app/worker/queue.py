import json
import sqlite3

from app.clock import now_iso

PRIORITY = {"media_fetch": 10, "url_fetch": 15, "profile_sync": 20, "page_fetch": 30}
MAX_ATTEMPTS = 3


def enqueue(conn: sqlite3.Connection, kind: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, payload, priority, status, created_at)"
        " VALUES (?, ?, ?, 'queued', ?)",
        (kind, json.dumps(payload, sort_keys=True), PRIORITY[kind], now_iso()),
    )
    return int(cur.lastrowid)


def enqueue_unique(conn: sqlite3.Connection, kind: str, payload: dict) -> int | None:
    encoded = json.dumps(payload, sort_keys=True)
    existing = conn.execute(
        "SELECT id FROM jobs WHERE kind=? AND payload=? AND status IN ('queued','running')",
        (kind, encoded),
    ).fetchone()
    if existing is not None:
        return None
    return enqueue(conn, kind, payload)


def claim_next(conn: sqlite3.Connection) -> sqlite3.Row | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued'"
            " ORDER BY priority, created_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
            (now_iso(), row["id"]),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()


def complete(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status='done', error=NULL, finished_at=? WHERE id=?",
        (now_iso(), job_id),
    )


def fail(conn: sqlite3.Connection, job_id: int, error: str, retryable: bool) -> None:
    row = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
    exhausted = row is None or row["attempts"] >= MAX_ATTEMPTS
    if retryable and not exhausted:
        conn.execute(
            "UPDATE jobs SET status='queued', started_at=NULL, error=? WHERE id=?",
            (error, job_id),
        )
        return
    conn.execute(
        "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
        (error, now_iso(), job_id),
    )


def requeue(conn: sqlite3.Connection, job_id: int) -> None:
    """Return a claimed job to the queue without spending an attempt.

    Used when the breaker trips mid-job: the failure is environmental,
    not the job's fault.
    """
    conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL,"
        " attempts=MAX(attempts-1, 0) WHERE id=?",
        (job_id,),
    )


def depth(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()["c"]
    )
