from fastapi import APIRouter, Depends, Request

from app.main_deps import get_conn_dep
from app.worker import queue

router = APIRouter()


@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    current = request.app.state.runtime.current
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "adapter": current.name,
        "token_configured": bool(current.settings.graph_token),
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
    }
