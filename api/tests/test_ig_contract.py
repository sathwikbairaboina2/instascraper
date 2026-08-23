import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter


def test_error_hierarchy():
    for exc in (t.IgNotFound, t.IgPrivate, t.IgRateLimited, t.IgChallenge, t.IgTransient):
        assert issubclass(exc, t.IgError)


def test_fake_returns_profile():
    fake = FakeAdapter()
    fake.add_profile("nike", post_count=3)
    p = fake.fetch_profile("nike")
    assert p.username == "nike"
    assert p.post_count == 3
    assert p.is_private is False


def test_fake_unknown_profile_raises_not_found():
    with pytest.raises(t.IgNotFound):
        FakeAdapter().fetch_profile("ghost")


def test_fake_paginates_and_signals_exhaustion():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=5)
    first = fake.fetch_page("nike", cursor=None, limit=2)
    assert [p.shortcode for p in first.posts] == ["nike-0", "nike-1"]
    assert first.next_cursor is not None
    second = fake.fetch_page("nike", cursor=first.next_cursor, limit=2)
    assert [p.shortcode for p in second.posts] == ["nike-2", "nike-3"]
    third = fake.fetch_page("nike", cursor=second.next_cursor, limit=2)
    assert [p.shortcode for p in third.posts] == ["nike-4"]
    assert third.next_cursor is None


def test_fake_fetch_media_writes_files(tmp_path):
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=1, child_count=3)
    saved = fake.fetch_media("nike-0", tmp_path)
    assert [s.child_idx for s in saved] == [1, 2, 3]
    for s in saved:
        assert s.path.exists()
        assert s.bytes > 0
    assert list(tmp_path.glob("*.part")) == []


def test_fake_records_call_windows():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.fetch_profile("nike")
    fake.fetch_profile("nike")
    assert [c.method for c in fake.calls] == ["fetch_profile", "fetch_profile"]
    assert fake.calls[0].ended <= fake.calls[1].started


def test_fake_raise_on_is_one_shot():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.raise_on("fetch_profile", t.IgRateLimited("429"))
    with pytest.raises(t.IgRateLimited):
        fake.fetch_profile("nike")
    assert fake.fetch_profile("nike").username == "nike"


def test_only_adapter_module_imports_instaloader():
    """Global constraint: the volatile dependency stays in one directory."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    allowed = {"adapter.py", "rate.py"}
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "instaloader" in p.read_text() and p.name not in allowed
    ]
    assert offenders == []
