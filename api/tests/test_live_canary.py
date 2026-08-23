import pytest

from app.config import load_settings
from app.ig.adapter import InstaloaderAdapter
from app.routes.health import run_canary

pytestmark = pytest.mark.live

CANARY_PROFILE = "instagram"


def test_real_instagram_still_matches_our_parsing(tmp_path):
    """The test that tells you Instagram rotated something.

    Run manually: pytest -m live
    """
    settings = load_settings()
    if not settings.ig_username:
        pytest.skip("IG_USERNAME not configured")

    result = run_canary(InstaloaderAdapter(settings), CANARY_PROFILE, tmp_path)

    assert result["ok"] is True, result["error"]
