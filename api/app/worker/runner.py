import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app import clock, db
from app.config import Settings
from app.ig import types as t
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer
from app.worker.resync import resync_tick

log = logging.getLogger("worker")


@dataclass
class HandlerContext:
    conn: object
    adapter: object
    settings: Settings
    pacer: Pacer
    # Meta's CDN does not spend the Graph quota, so thumbnails and avatars
    # wait on their own, far shorter, floor.
    cdn_pacer: Pacer
    enqueue: Callable[[str, dict], None]


Handler = Callable[[HandlerContext, dict], None]

IDLE_TIMEOUT = 5.0


class Worker(threading.Thread):
    """The one and only thread permitted to talk to Instagram."""

    def __init__(
        self,
        runtime,
        breaker: Breaker,
        pacer: Pacer,
        cdn_pacer: Pacer,
        handlers: dict[str, Handler],
    ):
        super().__init__(name="ig-worker", daemon=True)
        self.runtime = runtime
        self.breaker = breaker
        self.pacer = pacer
        self.cdn_pacer = cdn_pacer
        self.handlers = handlers
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self._next_resync: float | None = None

    # ---- lifecycle -----------------------------------------------------
    def shutdown(self, timeout: float = 5.0) -> None:
        self.stop_flag.set()
        self.wake.set()
        self.join(timeout=timeout)

    def drain(self, timeout: float = 5.0) -> None:
        """Test helper: block until nothing is queued or running."""
        conn = db.get_conn(self.runtime.current.settings)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if queue.depth(conn) == 0:
                return
            time.sleep(0.01)
        raise TimeoutError("queue did not drain")

    # ---- main loop -----------------------------------------------------
    def run(self) -> None:
        while not self.stop_flag.is_set():
            current = self.runtime.current
            conn = db.get_conn(current.settings)

            self._maybe_resync(conn, current.settings)

            wait = self.breaker.wait_seconds()
            if wait > 0:
                self.stop_flag.wait(min(wait, IDLE_TIMEOUT, self._until_resync(current.settings)))
                continue

            job = queue.claim_next(conn)
            if job is None:
                self.wake.wait(min(IDLE_TIMEOUT, self._until_resync(current.settings)))
                self.wake.clear()
                continue

            self._run_job(conn, current, job)

    # ---- scheduled resync ----------------------------------------------
    def _until_resync(self, settings: Settings) -> float:
        if settings.resync_interval_hours <= 0 or self._next_resync is None:
            return IDLE_TIMEOUT
        return max(0.01, self._next_resync - time.monotonic())

    def _maybe_resync(self, conn, settings: Settings) -> None:
        """Queue one overdue tracked profile at most every resync_check_seconds.

        Reads the live settings each pass, so it follows the adapter toggle.
        """
        if settings.resync_interval_hours <= 0:
            self._next_resync = None
            return
        now = time.monotonic()
        if self._next_resync is None:
            # First look shortly after start rather than a full period later.
            self._next_resync = now + min(1.0, settings.resync_check_seconds)
        if now < self._next_resync:
            return
        self._next_resync = now + settings.resync_check_seconds
        try:
            if resync_tick(conn, settings, self.breaker, clock.now()) is not None:
                self.wake.set()
        except Exception:  # noqa: BLE001 - a scheduler bug must not kill the worker
            log.exception("resync tick failed")

    def _run_job(self, conn, current, job) -> None:
        payload = json.loads(job["payload"])
        handler = self.handlers.get(job["kind"])
        started = time.monotonic()

        if handler is None:
            queue.fail(conn, job["id"], f"no handler for {job['kind']}", retryable=False)
            return

        ctx = HandlerContext(
            conn=conn,
            adapter=current.adapter,
            settings=current.settings,
            pacer=self.pacer,
            cdn_pacer=self.cdn_pacer,
            enqueue=lambda kind, p: self._enqueue(conn, kind, p),
        )

        try:
            handler(ctx, payload)
        except t.IgRateLimited as exc:
            queue.requeue(conn, job["id"])
            # IG_BACKOFF is a floor, never a licence to return sooner than asked.
            wait = max(current.settings.ig_backoff, exc.retry_after or 0)
            self.breaker.trip_temporary(wait, f"Rate limited: {exc}")
            self._log(job, payload, started, "rate_limited")
            return
        except t.IgChallenge as exc:
            self.breaker.trip_permanent(f"Instagram token invalid: {exc}")
            queue.requeue(conn, job["id"])
            self._log(job, payload, started, "challenge")
            return
        except t.IgQuotaSpent as exc:
            # Our own budget, so the breaker stays out of it: Graph work has
            # a separate quota and is nowhere near it.
            queue.fail(conn, job["id"], str(exc), retryable=False)
            self._log(job, payload, started, "quota_spent")
            return
        except (t.IgNotFound, t.IgPrivate) as exc:
            queue.fail(conn, job["id"], str(exc), retryable=False)
            self._log(job, payload, started, "terminal")
            return
        except t.IgTransient as exc:
            queue.fail(conn, job["id"], str(exc), retryable=True)
            self._log(job, payload, started, "transient")
            return
        except Exception as exc:  # noqa: BLE001 - a bug must not kill the worker
            log.exception("handler crashed")
            queue.fail(conn, job["id"], repr(exc), retryable=False)
            self._log(job, payload, started, "crashed")
            return

        queue.complete(conn, job["id"])
        self._log(job, payload, started, "done")

    def _enqueue(self, conn, kind: str, payload: dict) -> None:
        queue.enqueue_unique(conn, kind, payload)
        self.wake.set()

    def _log(self, job, payload: dict, started: float, outcome: str) -> None:
        log.info(
            json.dumps(
                {
                    "job_id": job["id"],
                    "kind": job["kind"],
                    "target": payload.get("username") or payload.get("shortcode"),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "outcome": outcome,
                }
            )
        )
