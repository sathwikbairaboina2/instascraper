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


def test_no_module_imports_instaloader():
    """Global constraint: the dependency is gone, not merely unused."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "instaloader" in p.read_text().lower()
    ]
    assert offenders == []


def test_credential_settings_are_gone():
    from app.config import Settings

    fields = set(Settings.__dataclass_fields__)
    assert not fields & {
        "ig_username",
        "ig_password",
        "session_dir",
        "anonymous",
        "max_sleep",
    }


def test_seeded_adapter_is_shared_by_make_adapter(settings):
    """The seed script and the running server must agree on the fake dataset.

    If make_adapter() returns an empty FakeAdapter, a seeded database refers
    to posts the server has never heard of and every media_fetch fails.
    """
    from app.ig.factory import make_adapter
    from app.ig.fake import seeded_adapter

    served = make_adapter(settings)
    canonical = seeded_adapter()

    assert set(served.profiles) == set(canonical.profiles)
    assert [p.shortcode for p in served.posts["nike"]] == [
        p.shortcode for p in canonical.posts["nike"]
    ]
    # every seeded shortcode must be fetchable
    for post in canonical.posts["nike"]:
        assert served._find_post(post.shortcode).shortcode == post.shortcode


def test_igpost_carries_media_sources():
    src = t.MediaSource(child_idx=0, url="https://cdn/x.jpg", mime="image/jpeg", is_video=False)
    post = t.IgPost(
        shortcode="abc",
        kind="image",
        taken_at_iso="2026-01-01T00:00:00+00:00",
        caption="",
        is_video=False,
        child_count=1,
        thumb_url="https://cdn/t.jpg",
        ig_url="https://instagram.com/p/abc/",
        sources=(src,),
    )
    assert post.sources[0].url == "https://cdn/x.jpg"


def test_igpost_sources_default_to_empty():
    post = t.IgPost(
        shortcode="abc",
        kind="image",
        taken_at_iso="2026-01-01T00:00:00+00:00",
        caption="",
        is_video=False,
        child_count=1,
        thumb_url="https://cdn/t.jpg",
        ig_url="https://instagram.com/p/abc/",
    )
    assert post.sources == ()


def test_fake_fetch_media_accepts_and_ignores_a_hint(tmp_path):
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=1)
    hint = t.MediaHint(username="nike", sources=(), captured_at="2026-01-01T00:00:00+00:00")
    saved = fake.fetch_media("nike-0", tmp_path, hint)
    assert [s.child_idx for s in saved] == [0]


def test_graph_adapter_satisfies_the_port(settings):
    """Every method the worker calls must exist with the right arity."""
    import inspect
    from dataclasses import replace

    from app.ig.graph import GraphAdapter

    adapter = GraphAdapter(replace(settings, adapter="graph", graph_version="v99.0"))

    for name in ("fetch_profile", "fetch_page", "fetch_media", "download_to", "login"):
        assert callable(getattr(adapter, name)), f"GraphAdapter is missing {name}"

    assert isinstance(adapter, t.IgAdapter)

    # The hint is optional, so existing call sites keep working.
    hint_param = inspect.signature(adapter.fetch_media).parameters["hint"]
    assert hint_param.default is None
