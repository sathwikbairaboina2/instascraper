import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app import db
from app.config import Settings
from app.ig import types as t
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer

log = logging.getLogger("worker")


@dataclass
class HandlerContext:
    conn: object
    adapter: object
    settings: Settings
    pacer: Pacer
    enqueue: Callable[[str, dict], None]


Handler = Callable[[HandlerContext, dict], None]

IDLE_TIMEOUT = 5.0


class Worker(threading.Thread):
    """The one and only thread permitted to talk to Instagram."""

    def __init__(
        self,
        settings: Settings,
        adapter,
        breaker: Breaker,
        pacer: Pacer,
        handlers: dict[str, Handler],
    ):
        super().__init__(name="ig-worker", daemon=True)
        self.settings = settings
        self.adapter = adapter
        self.breaker = breaker
        self.pacer = pacer
        self.handlers = handlers
        self.wake = threading.Event()
        self.stop_flag = threading.Event()

    # ---- lifecycle -----------------------------------------------------
    def shutdown(self, timeout: float = 5.0) -> None:
        self.stop_flag.set()
        self.wake.set()
        self.join(timeout=timeout)

    def drain(self, timeout: float = 5.0) -> None:
        """Test helper: block until nothing is queued or running."""
        conn = db.get_conn(self.settings)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if queue.depth(conn) == 0:
                return
            time.sleep(0.01)
        raise TimeoutError("queue did not drain")

    # ---- main loop -----------------------------------------------------
    def run(self) -> None:
        conn = db.get_conn(self.settings)
        while not self.stop_flag.is_set():
            wait = self.breaker.wait_seconds()
            if wait > 0:
                self.stop_flag.wait(min(wait, IDLE_TIMEOUT))
                continue

            job = queue.claim_next(conn)
            if job is None:
                self.wake.wait(IDLE_TIMEOUT)
                self.wake.clear()
                continue

            self._run_job(conn, job)

    def _run_job(self, conn, job) -> None:
        payload = json.loads(job["payload"])
        handler = self.handlers.get(job["kind"])
        started = time.monotonic()

        if handler is None:
            queue.fail(conn, job["id"], f"no handler for {job['kind']}", retryable=False)
            return

        ctx = HandlerContext(
            conn=conn,
            adapter=self.adapter,
            settings=self.settings,
            pacer=self.pacer,
            enqueue=lambda kind, p: self._enqueue(conn, kind, p),
        )

        try:
            handler(ctx, payload)
        except t.IgRateLimited as exc:
            queue.requeue(conn, job["id"])
            if self.settings.anonymous:
                # Waiting cannot fix an anonymous refusal -- Instagram declines
                # unauthenticated reads outright. Retrying on a timer would just
                # keep hitting them, which is how an IP gets blocked.
                self.breaker.trip_permanent(
                    "Instagram is refusing anonymous access; a dedicated account is required"
                )
                self._log(job, payload, started, "anonymous_refused")
                return
            # IG_BACKOFF is a floor, never a licence to return sooner than asked.
            wait = max(self.settings.ig_backoff, exc.retry_after or 0)
            self.breaker.trip_temporary(wait, f"Rate limited: {exc}")
            self._log(job, payload, started, "rate_limited")
            return
        except t.IgChallenge as exc:
            self.breaker.trip_permanent(f"Instagram session invalid: {exc}")
            queue.requeue(conn, job["id"])
            self._log(job, payload, started, "challenge")
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
