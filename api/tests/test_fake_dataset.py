"""The canonical fake dataset has to be able to demonstrate the app.

Every e2e assertion about trending is only as meaningful as the data under
it: without recent, tagged, engaged posts, an empty feed and a broken query
look identical.
"""
from datetime import datetime, timedelta, timezone

from app.ig.fake import seeded_adapter
from app.services import hashtags


def _all_posts(adapter):
    return [p for bucket in adapter.posts.values() for p in bucket]


def test_the_seeded_dataset_has_posts_from_the_last_day():
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    recent = [
        p for p in _all_posts(seeded_adapter())
        if datetime.fromisoformat(p.taken_at_iso) >= cutoff
    ]
    assert len(recent) >= 3


def test_the_seeded_dataset_has_posts_older_than_a_day_but_inside_the_week():
    now = datetime.now(timezone.utc)
    mid = [
        p for p in _all_posts(seeded_adapter())
        if now - timedelta(days=7) <= datetime.fromisoformat(p.taken_at_iso)
        < now - timedelta(days=1)
    ]
    assert len(mid) >= 3, "without these, day and week render identically"


def test_seeded_captions_carry_overlapping_hashtags():
    counts: dict[str, int] = {}
    for post in _all_posts(seeded_adapter()):
        for tag in hashtags.extract_tags(post.caption):
            counts[tag] = counts.get(tag, 0) + 1
    assert len(counts) >= 4, "a ranking of one tag proves nothing"
    assert max(counts.values()) >= 2, "a tag must span posts for ranking to matter"


def test_seeded_posts_carry_engagement():
    posts = _all_posts(seeded_adapter())
    assert all(p.like_count is not None for p in posts)
    assert all(p.comments_count is not None for p in posts)
    assert any(p.view_count for p in posts), "reels need views or the score is flat"
    assert all(p.view_count is None for p in posts if not p.is_video), (
        "views exist on reels and nowhere else"
    )


def test_engagement_differs_between_posts():
    likes = {p.like_count for p in _all_posts(seeded_adapter())}
    assert len(likes) > 1, "a flat dataset cannot demonstrate a ranking"


def test_dates_are_stable_within_one_adapter():
    adapter = seeded_adapter()
    first = [p.taken_at_iso for p in _all_posts(adapter)]
    second = [p.taken_at_iso for p in _all_posts(adapter)]
    assert first == second


def test_relative_dates_are_utc_with_a_plus_offset():
    # The endpoint compares taken_at as a string; a 'Z' here would sort
    # wrong against the cutoff and silently drop every seeded post.
    assert all(p.taken_at_iso.endswith("+00:00") for p in _all_posts(seeded_adapter()))
