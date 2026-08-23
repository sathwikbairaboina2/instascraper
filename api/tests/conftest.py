import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app import db


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        ig_username="tester",
        ig_password="secret",
        db_path=tmp_path / "app.db",
        media_dir=tmp_path / "media",
        session_dir=tmp_path / "session",
        out_dir=tmp_path / "out",
        page_size=4,
        ig_min_interval=0.05,
        ig_backoff=2,
        adapter="fake",
        anonymous=True,
        max_sleep=60,
    )


@pytest.fixture
def conn(settings):
    for d in (settings.media_dir, settings.session_dir, settings.out_dir):
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
