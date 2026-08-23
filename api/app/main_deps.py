from fastapi import Request

from app import db


def get_conn_dep(request: Request):
    """One connection per request, closed when the response is done.

    Deliberately NOT the thread-local connection: FastAPI may resolve this
    dependency on a different threadpool thread than the one that runs the
    endpoint, so a cached per-thread connection would be used off-thread.
    """
    conn = db.new_conn(request.app.state.settings)
    try:
        yield conn
    finally:
        conn.close()


def wake_worker(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.wake.set()
