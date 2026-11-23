"""IG_FAKE_DATASET lets a fake-adapter stack serve a fixture instead of the
nike seed, so a mock Instagram account can carry real-looking captions."""
import json
from pathlib import Path

import pytest

from app.ig.fake import load_dataset, seeded_adapter
from app.worker import handlers
from app.worker.runner import HandlerContext

JOBS = Path(__file__).parent / "fixtures" / "fake" / "jobs_mock.json"


class _NoWait:
    def wait(self) -> None:
        pass


def test_load_dataset_reads_profiles_and_posts_verbatim():
    adapter = load_dataset(JOBS)

    assert list(adapter.profiles) == ["hiring.daily.mock"]
    profile = adapter.profiles["hiring.daily.mock"]
    assert profile.full_name == "Hiring Daily (mock)"
    posts = adapter.posts["hiring.daily.mock"]
    assert [p.shortcode for p in posts] == [f"hiring.daily.mock-{i}" for i in range(3)]
    assert posts[0].caption.startswith("Hiring: Software Engineer I\nCompany: Zoho\n")
    assert "Salary: 6-9 LPA" in posts[0].caption
    assert all("Salary" not in p.caption for p in posts[1:])
    assert "Location: Remote" in posts[1].caption
    assert all(p.kind == "image" and not p.is_video for p in posts)
    assert profile.post_count == 3


def test_load_dataset_missing_file_names_the_path(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError) as err:
        load_dataset(missing)
    assert str(missing) in str(err.value)


def test_load_dataset_invalid_json_names_the_path(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as err:
        load_dataset(bad)
    assert str(bad) in str(err.value)


def test_load_dataset_wrong_shape_names_the_path(tmp_path):
    bad = tmp_path / "shape.json"
    bad.write_text(json.dumps({"profiles": [{"full_name": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError) as err:
        load_dataset(bad)
    assert str(bad) in str(err.value)


def test_seeded_adapter_keeps_the_nike_seed_when_unset(monkeypatch):
    monkeypatch.delenv("IG_FAKE_DATASET", raising=False)
    adapter = seeded_adapter()
    assert list(adapter.profiles) == ["nike"]
    assert len(adapter.posts["nike"]) == 3 + 3 + 2 + 2


def test_seeded_adapter_loads_the_dataset_when_set(monkeypatch):
    monkeypatch.setenv("IG_FAKE_DATASET", str(JOBS))
    adapter = seeded_adapter()
    assert list(adapter.profiles) == ["hiring.daily.mock"]


def test_seeded_adapter_with_a_bad_path_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("IG_FAKE_DATASET", str(tmp_path / "gone.json"))
    with pytest.raises(ValueError):
        seeded_adapter()


def test_sync_and_page_fetch_store_the_captions(settings, conn):
    adapter = load_dataset(JOBS)
    ctx = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=_NoWait(),
        cdn_pacer=_NoWait(),
        enqueue=lambda kind, payload: None,
    )

    handlers.handle_profile_sync(ctx, {"username": "hiring.daily.mock"})
    handlers.handle_page_fetch(ctx, {"username": "hiring.daily.mock"})
    handlers.handle_page_fetch(ctx, {"username": "hiring.daily.mock"})

    rows = conn.execute(
        "SELECT shortcode, caption FROM media_items ORDER BY shortcode"
    ).fetchall()
    assert [r["shortcode"] for r in rows] == [f"hiring.daily.mock-{i}" for i in range(3)]
    assert rows[0]["caption"].startswith("Hiring: Software Engineer I")
    assert "Company: Freshworks" in rows[1]["caption"]
