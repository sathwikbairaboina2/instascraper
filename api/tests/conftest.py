import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app import db


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "app.db",
        media_dir=tmp_path / "media",
        out_dir=tmp_path / "out",
        page_size=4,
        first_page_size=2,
        ig_min_interval=0.05,
        cdn_min_interval=0.0,
        ig_backoff=2,
        adapter="fake",
        graph_token="",
        graph_user_id="",
        graph_version="v99.0",
        graph_refresh_pages=2,
        graph_usage_limit=90.0,
        reel_max_per_hour=20,
        reel_max_per_day=100,
        reel_timeout=5.0,
        reel_min_interval=0.0,
        # The older resync tests exercise interval mode; daily tests opt in.
        resync_daily_at="",
    )


@pytest.fixture
def conn(settings):
    for d in (settings.media_dir, settings.out_dir):
        d.mkdir(parents=True, exist_ok=True)
    c = db.get_conn(settings)
    db.init_schema(c)
    yield c
    c.close()
    db.reset_thread_state()


@pytest.fixture
def adapter():
    from app.ig.fake import FakeAdapter

    fake = FakeAdapter()
    fake.add_profile("nike", post_count=10)
    fake.add_posts("nike", count=10)
    return fake


@pytest.fixture
def client(settings, conn, adapter):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings=settings, adapter=adapter, start_worker=False)
    with TestClient(app) as c:
        c.app_state = app.state  # type: ignore[attr-defined]
        yield c
