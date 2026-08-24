"""Do not retry sooner than Meta asked, and do not loop forever.

Retrying at a shorter interval than the server requested is the behaviour
that escalates a rate limit into a blocked account.
"""
import pytest

from app.ig import graph, types as t
from app.ig.fake import FakeAdapter
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer
from app.runtime import RuntimeConfig
from app.worker.runner import Worker


def _settings(settings, **over):
    return settings.__class__(**{**settings.__dict__, **over})


def test_rate_limited_carries_the_requested_wait():
    exc = t.IgRateLimited("slow down", retry_after=1818)
    assert exc.retry_after == 1818


def test_breaker_honours_the_wait_meta_asked_for():
    """Meta sends no Retry-After, but throttling replies estimate the wait."""
    headers = {"x-business-use-case-usage": '{"1":[{"estimated_time_to_regain_access":3}]}'}
    exc = graph.classify(400, {"error": {"code": 4, "message": "throttled"}}, headers)

    assert isinstance(exc, t.IgRateLimited)
    assert exc.retry_after == 180.0


def test_our_own_errors_pass_through_the_adapter_untouched(settings):
    """A classified error must not be re-wrapped as a generic transient one."""
    from dataclasses import replace

    from app.ig.graph import GraphAdapter

    original = t.IgRateLimited("slow down", retry_after=900)

    def transport(url, headers):
        raise original

    adapter = GraphAdapter(
        replace(settings, graph_token="TOK", graph_user_id="SELF", graph_version="v99.0"),
        transport=transport,
    )
    with pytest.raises(t.IgRateLimited) as caught:
        adapter.fetch_profile("nike")
    assert caught.value is original


def test_breaker_waits_at_least_as_long_as_meta_asked(settings, conn):
    """IG_BACKOFF is a floor, never a way to retry sooner than requested."""
    s = _settings(settings, ig_backoff=900)
    breaker = Breaker()

    def handler(ctx, payload):
        raise t.IgRateLimited("429", retry_after=1818)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    worker = Worker(
        RuntimeConfig.fixed(s, FakeAdapter()), breaker, Pacer(0.0), {"profile_sync": handler}
    )
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    assert breaker.wait_seconds() > 1700, "retried sooner than Meta asked"


def test_backoff_floor_still_applies_when_no_wait_is_given(settings, conn):
    s = _settings(settings, ig_backoff=900)
    breaker = Breaker()

    def handler(ctx, payload):
        raise t.IgRateLimited("429")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    worker = Worker(
        RuntimeConfig.fixed(s, FakeAdapter()), breaker, Pacer(0.0), {"profile_sync": handler}
    )
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    assert 800 < breaker.wait_seconds() <= 900


def test_a_dead_token_trips_the_breaker_permanently(settings, conn):
    """Waiting cannot fix a revoked token, so retrying only adds load.

    This replaces the old anonymous-refusal case: Graph has no anonymous
    mode, and a missing or dead token is the equivalent terminal state.
    """
    breaker = Breaker()
    calls = []

    def handler(ctx, payload):
        calls.append(1)
        raise t.IgChallenge("Error validating access token")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    queue.enqueue(conn, "profile_sync", {"username": "adidas"})
    worker = Worker(
        RuntimeConfig.fixed(settings, FakeAdapter()),
        breaker,
        Pacer(0.0),
        {"profile_sync": handler},
    )
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    state = breaker.state()
    assert len(calls) == 1, "kept calling Meta with a dead token"
    assert state["permanent"] is True
