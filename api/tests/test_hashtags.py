"""The rules from the spec, one test each.

Extraction is where this feature is most likely to be quietly wrong: a
regex that also matches a url fragment produces a ranking that looks
plausible and is not.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import hashtags


def test_extracts_tags_in_order():
    assert hashtags.extract_tags("morning run #nike #justdoit") == ["nike", "justdoit"]


def test_folds_case_so_one_tag_is_one_row():
    assert hashtags.extract_tags("#Nike #NIKE #nike") == ["nike"]


def test_counts_a_repeated_tag_once():
    assert hashtags.extract_tags("#sale #sale #sale") == ["sale"]


def test_trailing_punctuation_is_not_part_of_the_tag():
    assert hashtags.extract_tags("#nike, #run. #fit!") == ["nike", "run", "fit"]


def test_keeps_non_ascii_tags():
    # Devanagari vowel signs are combining marks, and a naive \w class cuts
    # the tag at the first one -- indexing #नाइकी as #न.
    assert hashtags.extract_tags("#नाइकी") == ["नाइकी"]


def test_greek_sigma_folds_to_one_tag():
    # casefold maps final sigma to plain sigma, so the three spellings of
    # this word are one tag. That is the point; the stored form ending in a
    # non-final sigma is the price.
    assert hashtags.extract_tags("#κόσμος #ΚΌΣΜΟΣ") == ["κόσμοσ"]


def test_ignores_a_hash_inside_a_word_or_url():
    assert hashtags.extract_tags("see example.com/#anchor or C#") == []


def test_ignores_a_bare_hash():
    assert hashtags.extract_tags("# #, #") == []


def test_a_newline_separates_tags():
    assert hashtags.extract_tags("caption\n#nike\n#run") == ["nike", "run"]


@pytest.mark.parametrize("caption", [None, "", "no tags here"])
def test_captions_without_tags_yield_nothing(caption):
    assert hashtags.extract_tags(caption) == []


def test_window_since_subtracts_the_right_span():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    assert hashtags.window_since("day", now) == "2026-08-24T12:00:00+00:00"
    assert hashtags.window_since("week", now) == "2026-08-18T12:00:00+00:00"


def test_window_since_rejects_anything_else():
    with pytest.raises(ValueError):
        hashtags.window_since("month")


def test_since_is_utc_with_a_plus_offset():
    # The endpoint compares this against taken_at as a string, so the format
    # has to match what the writers emit. A 'Z' suffix sorts before '+00:00'
    # and would silently exclude posts.
    assert hashtags.window_since("day").endswith("+00:00")


def _row(caption, likes=None, comments=None, views=None):
    return {
        "caption": caption,
        "like_count": likes,
        "comments_count": comments,
        "view_count": views,
    }


def test_rank_sums_engagement_across_posts():
    items = hashtags.rank([
        _row("#nike", likes=10, comments=2, views=None),
        _row("#nike", likes=5, comments=1, views=100),
    ])
    assert items == [{
        "tag": "nike",
        "score": 118,
        "like_count": 15,
        "comments_count": 3,
        "view_count": 100,
        "post_count": 2,
    }]


def test_rank_treats_missing_engagement_as_zero():
    items = hashtags.rank([_row("#nike")])
    assert items[0]["score"] == 0
    assert items[0]["post_count"] == 1


def test_rank_orders_by_score_then_posts_then_tag():
    items = hashtags.rank([
        _row("#low", likes=1),
        _row("#high", likes=100),
        _row("#tie #alpha", likes=50),
        _row("#tie", likes=0),
    ])
    # #tie: 50 over two posts. #alpha: 50 over one. Same score, more posts wins.
    assert [i["tag"] for i in items] == ["high", "tie", "alpha", "low"]


def test_rank_breaks_a_full_tie_alphabetically():
    items = hashtags.rank([_row("#beta #alpha", likes=7)])
    assert [i["tag"] for i in items] == ["alpha", "beta"]


def test_rank_ignores_posts_with_no_tags():
    assert hashtags.rank([_row("nothing here", likes=999)]) == []
