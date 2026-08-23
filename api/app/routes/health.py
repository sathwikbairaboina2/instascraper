import tempfile
from pathlib import Path

from fastapi import APIRouter, Query, Request

router = APIRouter()

DEFAULT_CANARY = "instagram"


def run_canary(adapter, username: str, workdir: Path) -> dict:
    """Prove the adapter still understands Instagram, end to end.

    Shared by GET /api/health/canary and the `live` test so the two can
    never drift.
    """
    checks = {"profile": False, "page": False, "media": False}
    try:
        profile = adapter.fetch_profile(username)
        checks["profile"] = bool(profile.username)

        page = adapter.fetch_page(username, None, 3)
        checks["page"] = len(page.posts) > 0
        if not page.posts:
            return {"ok": False, "checks": checks, "error": "profile returned no posts"}

        saved = adapter.fetch_media(page.posts[0].shortcode, workdir)
        checks["media"] = bool(saved) and all(s.bytes > 0 for s in saved)
    except Exception as exc:  # noqa: BLE001 - a canary reports, it does not raise
        return {"ok": False, "checks": checks, "error": f"{type(exc).__name__}: {exc}"}

    return {"ok": all(checks.values()), "checks": checks, "error": None}


@router.get("/health/canary")
def canary(request: Request, username: str = Query(DEFAULT_CANARY)):
    with tempfile.TemporaryDirectory() as tmp:
        return run_canary(request.app.state.adapter, username, Path(tmp))


@router.post("/health/clear-breaker")
def clear_breaker(request: Request):
    request.app.state.breaker.clear()
    return {"cleared": True}
