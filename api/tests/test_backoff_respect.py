"""Do not retry sooner than Instagram asked, and do not loop forever.

Retrying at a shorter interval than the server requested is the behaviour
that escalates a rate limit into a blocked IP.
"""
import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer
from app.worker.runner import Worker


def _settings(settings, **over):
    return settings.__class__(**{**settings.__dict__, **over})


def test_rate_limited_carries_the_requested_wait():
    exc = t.IgRateLimited("slow down", retry_after=1818)
    assert exc.retry_after == 1818


def test_rate_controller_reports_the_wait_it_refused():
    from app.ig.rate import PacedRateController

    rc = PacedRateController(context=None, min_interval=3, max_sleep=60, sleep=lambda _: None)
    with pytest.raises(t.IgRateLimited) as exc:
        rc.sleep(1818)
    assert exc.value.retry_after == pytest.approx(1818)


def test_classify_passes_our_own_errors_through_untouched():
    from app.ig.adapter import classify

    original = t.IgRateLimited("slow down", retry_after=900)
    assert classify(original) is original


def test_breaker_waits_at_least_as_long_as_instagram_asked(settings, conn):
    """IG_BACKOFF is a floor, never a way to retry sooner than requested."""
    s = _settings(settings, ig_backoff=900, anonymous=False)
    breaker = Breaker()

    def handler(ctx, payload):
        raise t.IgRateLimited("429", retry_after=1818)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    worker = Worker(s, FakeAdapter(), breaker, Pacer(0.0), {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    assert breaker.wait_seconds() > 1700, "retried sooner than Instagram asked"


def test_backoff_floor_still_applies_when_no_wait_is_given(settings, conn):
    s = _settings(settings, ig_backoff=900, anonymous=False)
    breaker = Breaker()

    def handler(ctx, payload):
        raise t.IgRateLimited("429")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    worker = Worker(s, FakeAdapter(), breaker, Pacer(0.0), {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    assert 800 < breaker.wait_seconds() <= 900


def test_anonymous_rate_limit_stops_instead_of_looping(settings, conn):
    """Waiting cannot fix an anonymous refusal, so retrying only adds load."""
    s = _settings(settings, anonymous=True)
    breaker = Breaker()
    calls = []

    def handler(ctx, payload):
        calls.append(1)
        raise t.IgRateLimited("429", retry_after=1818)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    queue.enqueue(conn, "profile_sync", {"username": "adidas"})
    worker = Worker(s, FakeAdapter(), breaker, Pacer(0.0), {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=1.5)
    worker.shutdown()

    state = breaker.state()
    assert len(calls) == 1, "kept hitting Instagram while anonymous"
    assert state["permanent"] is True
    assert "anonymous" in (state["reason"] or "").lower()
