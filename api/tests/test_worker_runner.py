import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext, Worker


@pytest.fixture
def worker_env(settings, conn):
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=6)
    breaker = Breaker()
    pacer = Pacer(min_interval=settings.ig_min_interval)
    return settings, conn, adapter, breaker, pacer


def _run(settings, adapter, breaker, pacer, handlers, conn):
    worker = Worker(settings, adapter, breaker, pacer, handlers)
    worker.start()
    worker.wake.set()
    worker.drain(timeout=10)
    worker.shutdown()
    return worker


def test_instagram_calls_never_overlap_and_respect_min_interval(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env

    def handler(ctx: HandlerContext, payload: dict):
        ctx.pacer.wait()
        ctx.adapter.fetch_profile("nike")

    for _ in range(5):
        queue.enqueue(conn, "profile_sync", {"username": "nike"})

    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    assert len(adapter.calls) == 5
    windows = sorted((c.started, c.ended) for c in adapter.calls)
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start >= prev_end, "two Instagram calls overlapped"
        assert next_start - prev_end >= settings.ig_min_interval * 0.9


def test_media_fetch_preempts_queued_page_fetches(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    order = []

    def record(kind):
        def handler(ctx, payload):
            order.append((kind, payload))

        return handler

    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.enqueue(conn, "page_fetch", {"n": 3})
    queue.enqueue(conn, "media_fetch", {"sc": "A"})

    _run(
        settings,
        adapter,
        breaker,
        pacer,
        {"page_fetch": record("page"), "media_fetch": record("media")},
        conn,
    )

    assert order[0] == ("media", {"sc": "A"})


def test_rate_limit_trips_breaker_requeues_job_and_resumes(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    settings = settings.__class__(**{**settings.__dict__, "ig_backoff": 1})
    attempts = []

    def handler(ctx, payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise t.IgRateLimited("429")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert len(attempts) == 2
    assert row["status"] == "done"
    assert row["attempts"] == 1, "a breaker trip must not burn a retry"


def test_challenge_trips_breaker_permanently_and_stops_work(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    calls = []

    def handler(ctx, payload):
        calls.append(payload)
        raise t.IgChallenge("checkpoint_required")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    queue.enqueue(conn, "profile_sync", {"username": "adidas"})

    worker = Worker(settings, adapter, breaker, pacer, {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=2)
    worker.shutdown()

    assert len(calls) == 1, "worker kept hammering after a challenge"
    assert breaker.state()["permanent"] is True
    assert queue.depth(conn) == 2


def test_terminal_error_fails_job_without_retry(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env

    def handler(ctx, payload):
        raise t.IgNotFound("ghost")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 1


def test_transient_error_retries_to_max_then_fails(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    calls = []

    def handler(ctx, payload):
        calls.append(1)
        raise t.IgTransient("connection reset")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert len(calls) == queue.MAX_ATTEMPTS
    assert row["status"] == "failed"


def test_handler_can_enqueue_follow_up_work(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    seen = []

    def sync(ctx, payload):
        ctx.enqueue("page_fetch", {"username": payload["username"]})

    def page(ctx, payload):
        seen.append(payload)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": sync, "page_fetch": page}, conn)

    assert seen == [{"username": "nike"}]
