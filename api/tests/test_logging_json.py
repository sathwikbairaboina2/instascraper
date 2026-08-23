"""Boot and job logs must be machine-readable.

Spec section 8 promises structured JSON logs. A dict interpolated with %s
emits Python repr (single quotes), which looks like JSON in a terminal and
fails every parser.
"""
import json
import logging

from app.ig.fake import FakeAdapter
from app.main import create_app


def test_sweep_boot_line_is_valid_json(settings, caplog):
    from fastapi.testclient import TestClient

    with caplog.at_level(logging.INFO):
        app = create_app(settings=settings, adapter=FakeAdapter(), start_worker=False)
        with TestClient(app):
            pass

    sweep_lines = [r.getMessage() for r in caplog.records if '"event": "sweep"' in r.getMessage()]
    assert sweep_lines, "no sweep line emitted on boot"
    parsed = json.loads(sweep_lines[0])
    assert parsed["event"] == "sweep"
    assert {"parts", "items", "jobs"} <= parsed.keys()


def test_worker_job_lines_are_valid_json(settings, conn, caplog):
    from app.worker import queue
    from app.worker.breaker import Breaker
    from app.worker.pacer import Pacer
    from app.worker.runner import Worker

    queue.enqueue(conn, "profile_sync", {"username": "nike"})

    with caplog.at_level(logging.INFO, logger="worker"):
        worker = Worker(
            settings, FakeAdapter(), Breaker(), Pacer(0.0),
            {"profile_sync": lambda ctx, payload: None},
        )
        worker.start()
        worker.wake.set()
        worker.drain(timeout=10)
        worker.shutdown()

    lines = [r.getMessage() for r in caplog.records if r.name == "worker"]
    assert lines, "worker emitted no job lines"
    for line in lines:
        parsed = json.loads(line)
        assert {"job_id", "kind", "outcome", "duration_ms"} <= parsed.keys()
