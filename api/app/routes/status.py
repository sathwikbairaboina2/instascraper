from fastapi import APIRouter, Depends, Request

from app.main_deps import get_conn_dep
from app.worker import queue

router = APIRouter()


@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "anonymous": request.app.state.settings.anonymous,
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
    }
