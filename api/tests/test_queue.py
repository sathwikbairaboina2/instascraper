import json

from app.worker import queue


def test_enqueue_returns_id_and_sets_priority(conn):
    job_id = queue.enqueue(conn, "page_fetch", {"username": "nike"})
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["kind"] == "page_fetch"
    assert row["priority"] == 30
    assert row["status"] == "queued"
    assert json.loads(row["payload"]) == {"username": "nike"}


def test_claim_next_respects_priority_then_age(conn):
    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.enqueue(conn, "media_fetch", {"n": 3})
    queue.enqueue(conn, "profile_sync", {"n": 4})

    order = []
    while (job := queue.claim_next(conn)) is not None:
        order.append(json.loads(job["payload"])["n"])
        queue.complete(conn, job["id"])
    assert order == [3, 4, 1, 2]


def test_claim_next_marks_running_and_counts_attempt(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    job = queue.claim_next(conn)
    assert job["id"] == job_id
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "running"
    assert row["attempts"] == 1
    assert row["started_at"] is not None


def test_claim_next_returns_none_when_empty(conn):
    assert queue.claim_next(conn) is None


def test_a_claimed_job_is_not_claimed_again(conn):
    queue.enqueue(conn, "media_fetch", {"sc": "A"})
    assert queue.claim_next(conn) is not None
    assert queue.claim_next(conn) is None


def test_enqueue_unique_skips_duplicates(conn):
    first = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    second = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    assert first is not None
    assert second is None
    queue.claim_next(conn)
    assert queue.enqueue_unique(conn, "media_fetch", {"sc": "A"}) is None


def test_enqueue_unique_allows_after_completion(conn):
    job_id = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)
    queue.complete(conn, job_id)
    assert queue.enqueue_unique(conn, "media_fetch", {"sc": "A"}) is not None


def test_fail_retries_until_max_attempts(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    for _ in range(queue.MAX_ATTEMPTS - 1):
        queue.claim_next(conn)
        queue.fail(conn, job_id, "boom", retryable=True)
        assert conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()["status"] == "queued"

    queue.claim_next(conn)
    queue.fail(conn, job_id, "boom", retryable=True)
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "boom"
    assert row["finished_at"] is not None


def test_fail_non_retryable_is_terminal_immediately(conn):
    job_id = queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    queue.claim_next(conn)
    queue.fail(conn, job_id, "not found", retryable=False)
    assert conn.execute(
        "SELECT status FROM jobs WHERE id=?", (job_id,)
    ).fetchone()["status"] == "failed"


def test_requeue_does_not_consume_an_attempt(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)
    queue.requeue(conn, job_id)
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["started_at"] is None


def test_depth_counts_queued_and_running(conn):
    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.claim_next(conn)
    assert queue.depth(conn) == 2
