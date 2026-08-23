from fastapi import Request

from app import db


def get_conn_dep(request: Request):
    return db.get_conn(request.app.state.settings)


def wake_worker(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.wake.set()
