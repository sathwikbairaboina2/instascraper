import json
from pathlib import Path

import pytest

from app.ig import graph_map, types as t

FIXTURES = Path(__file__).parent / "fixtures" / "graph"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_profile_maps_every_field():
    profile = graph_map.profile_from_payload(load("profile.json"))
    assert profile.username == "nike"
    assert profile.user_id == "17841400000000000"
    assert profile.full_name == "Nike"
    assert profile.biography == "Just Do It."
    assert profile.post_count == 1669
    assert profile.avatar_url.endswith("avatar.jpg")


def test_profile_is_never_private():
    """Business Discovery only returns public Business/Creator accounts."""
    assert graph_map.profile_from_payload(load("profile.json")).is_private is False


def test_profile_tolerates_missing_optional_fields():
    payload = {"business_discovery": {"id": "1", "username": "x"}}
    profile = graph_map.profile_from_payload(payload)
    assert profile.full_name == ""
    assert profile.biography == ""
    assert profile.post_count == 0


@pytest.mark.parametrize(
    "permalink,expected",
    [
        ("https://www.instagram.com/p/DcVY5dZm_Pv/", "DcVY5dZm_Pv"),
        ("https://www.instagram.com/reel/Db6EzJxRewC/", "Db6EzJxRewC"),
        ("https://www.instagram.com/tv/DbJCoXguNF5/", "DbJCoXguNF5"),
    ],
)
def test_shortcode_parses_from_permalink(permalink, expected):
    assert graph_map.shortcode_from_permalink(permalink) == expected


def test_shortcode_rejects_an_unrecognised_permalink():
    with pytest.raises(ValueError):
        graph_map.shortcode_from_permalink("https://example.com/nope")


def test_image_post_maps_to_a_single_source():
    page = graph_map.page_from_payload(load("media_page.json"))
    post = page.posts[0]
    assert post.shortcode == "AAAAAAAAAAA"
    assert post.kind == "image"
    assert post.is_video is False
    assert post.child_count == 1
    assert post.thumb_url.endswith("img1.jpg")
    assert post.sources == (
        t.MediaSource(0, "https://scontent.cdninstagram.com/img1.jpg", "image/jpeg", False),
    )


def test_timestamp_is_normalised_to_iso_with_a_colon_offset():
    post = graph_map.page_from_payload(load("media_page.json")).posts[0]
    assert post.taken_at_iso == "2026-08-20T14:03:11+00:00"


def test_reel_is_distinguished_from_plain_video_by_its_permalink():
    post = graph_map.page_from_payload(load("media_page.json")).posts[1]
    assert post.kind == "reel"
    assert post.is_video is True
    # A video's thumbnail is the still, but its source is the MP4.
    assert post.thumb_url.endswith("thumb2.jpg")
    assert post.sources[0].url.endswith("vid2.mp4")
    assert post.sources[0].mime == "video/mp4"


def test_carousel_children_become_one_indexed_sources():
    post = graph_map.page_from_payload(load("media_page.json")).posts[2]
    assert post.kind == "carousel"
    assert post.child_count == 2
    assert [s.child_idx for s in post.sources] == [1, 2]
    assert post.sources[0].mime == "image/jpeg"
    assert post.sources[1].mime == "video/mp4"
    assert post.sources[1].is_video is True


def test_page_reports_the_after_cursor_when_more_remain():
    assert graph_map.page_from_payload(load("media_page.json")).next_cursor == "CURSOR_AFTER_1"


def test_final_page_reports_exhaustion_despite_carrying_a_cursor():
    """Meta still sends an `after` cursor on the last page; only `next` is
    proof that another page exists."""
    assert graph_map.page_from_payload(load("media_last_page.json")).next_cursor is None


def test_absent_media_edge_is_an_empty_exhausted_page():
    page = graph_map.page_from_payload({"business_discovery": {"username": "x"}})
    assert page.posts == []
    assert page.next_cursor is None


def test_reel_is_classified_from_the_product_type_not_the_url():
    """The permalink shape is a proxy; media_product_type is the definition."""
    node = {
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "media_url": "https://cdn/v.mp4",
        "thumbnail_url": "https://cdn/t.jpg",
        # A /p/ permalink on a reel: the old heuristic would miss this.
        "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "reel"


def test_feed_video_is_not_a_reel():
    node = {
        "media_type": "VIDEO",
        "media_product_type": "FEED",
        "media_url": "https://cdn/v.mp4",
        "thumbnail_url": "https://cdn/t.jpg",
        "permalink": "https://www.instagram.com/reel/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "video"


def test_a_missing_product_type_falls_back_to_the_media_type():
    """Older recorded payloads carry no product type; they must still map."""
    node = {
        "media_type": "IMAGE",
        "media_url": "https://cdn/i.jpg",
        "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "image"


def test_profile_carries_the_follower_count():
    profile = graph_map.profile_from_payload(load("profile.json"))
    assert profile.followers_count == 291399778


def test_a_profile_without_a_follower_count_maps_to_zero():
    payload = {"business_discovery": {"username": "x", "id": "1", "media_count": 0}}
    assert graph_map.profile_from_payload(payload).followers_count == 0


def test_a_reel_with_no_media_url_yields_no_sources():
    """Business Discovery never returns media_url for a reel.

    Verified live against thevarunmayya, nike and natgeo: FEED items always
    carry it, REELS never do. An empty string here became a bare httpx
    'Request URL is missing an http:// or https:// protocol'.
    """
    node = {
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "thumbnail_url": "https://cdn/t.jpg",
        "permalink": "https://www.instagram.com/reel/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).sources == ()


def test_a_carousel_keeps_the_children_that_do_have_urls():
    """A slide without a url must not shift the others' child_idx."""
    node = {
        "media_type": "CAROUSEL_ALBUM",
        "media_product_type": "FEED",
        "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
        "children": {
            "data": [
                {"media_type": "IMAGE", "media_url": "https://cdn/a.jpg"},
                {"media_type": "VIDEO", "thumbnail_url": "https://cdn/b.jpg"},
                {"media_type": "IMAGE", "media_url": "https://cdn/c.jpg"},
            ]
        },
    }
    sources = graph_map.post_from_node(node).sources
    assert [s.child_idx for s in sources] == [1, 3]
