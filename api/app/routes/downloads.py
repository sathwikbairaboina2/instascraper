from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.main_deps import get_conn_dep
from app.services import downloads

router = APIRouter()


class DownloadBody(BaseModel):
    shortcodes: list[str]
    base: str


@router.post("/downloads")
def create_download(body: DownloadBody, request: Request, conn=Depends(get_conn_dep)):
    if not body.shortcodes:
        raise HTTPException(status_code=400, detail={"message": "no items selected"})
    try:
        return downloads.run(conn, request.app.state.settings, body.shortcodes, body.base)
    except downloads.NotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "some items are not cached yet", "not_ready": exc.shortcodes},
        ) from exc
