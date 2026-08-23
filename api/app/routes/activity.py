from fastapi import APIRouter, Depends, Query

from app.main_deps import get_conn_dep
from app.services import activity

router = APIRouter()


@router.get("/activity")
def get_activity(limit: int = Query(100, ge=1, le=1000), conn=Depends(get_conn_dep)):
    return {"items": activity.recent(conn, limit)}
