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
