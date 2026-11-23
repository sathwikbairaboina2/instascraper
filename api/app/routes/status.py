from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import runtime as rt
from app.clock import now_iso
from app.ig.factory import make_adapter
from app.main_deps import get_conn_dep
from app.services import quota
from app.worker import queue
from app.worker.resync import due_profiles

router = APIRouter()


@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    current = request.app.state.runtime.current
    # The fake adapter never calls Meta. A 0% there would read as a real
    # measurement rather than an absent one.
    usage = getattr(current.adapter, "usage", None)
    # Our own ledger, so unlike Meta's quota the reset time is a fact rather
    # than an estimate.
    now = now_iso()
    settings = current.settings
    reel_limits = {
        "hour": quota.window(conn, quota.REEL, 3600, settings.reel_max_per_hour, now),
        "day": quota.window(conn, quota.REEL, 86400, settings.reel_max_per_day, now),
    }
    next_due = None
    if settings.resync_interval_hours > 0:
        due = due_profiles(conn, now, settings.resync_interval_hours)
        if due:
            row = conn.execute(
                "SELECT last_synced_at FROM profiles WHERE username=?", (due[0],)
            ).fetchone()
            next_due = {"username": due[0], "last_synced_at": row["last_synced_at"]}
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "adapter": current.name,
        "token_configured": bool(current.settings.graph_token),
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
        "usage": usage,
        "reel_limits": reel_limits,
        "resync": {
            "interval_hours": settings.resync_interval_hours,
            "check_seconds": settings.resync_check_seconds,
            "next_due": next_due,
        },
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
