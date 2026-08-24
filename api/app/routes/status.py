from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import runtime as rt
from app.ig.factory import make_adapter
from app.main_deps import get_conn_dep
from app.worker import queue

router = APIRouter()


@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    current = request.app.state.runtime.current
    # The fake adapter never calls Meta. A 0% there would read as a real
    # measurement rather than an absent one.
    usage = getattr(current.adapter, "usage", None)
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "adapter": current.name,
        "token_configured": bool(current.settings.graph_token),
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
        "usage": usage,
    }


class AdapterBody(BaseModel):
    adapter: str


@router.post("/adapter")
def set_adapter(request: Request, body: AdapterBody):
    """Switch the live adapter, and with it the data root it reads and writes."""
    holder = request.app.state.runtime
    name = body.adapter
    if name not in rt.NAMES:
        raise HTTPException(status_code=400, detail=f"unknown adapter {name!r}")
    if name == holder.current.name:
        return {"adapter": name}

    # Everything that can fail happens before the swap, so a failed switch
    # leaves the process exactly where it was.
    settings = rt.settings_for(holder.base, name)
    adapter = make_adapter(settings)
    rt.prepare_data_root(settings)

    holder.swap(rt.Runtime(name, settings, adapter))
    request.app.state.breaker.clear()
    # Persisted last: a crash before this must not record a choice that
    # never took effect.
    rt.write_selection(holder.base, name)
    return {"adapter": name}
