"""Opt-in probe that Meta still answers the way the fixtures claim.

Skipped unless IG_GRAPH_TOKEN is set, so the default suite never touches
the network. Asserts shape, never content: a canary that fails because an
account posted something new is a canary nobody trusts.
"""

import os

import pytest

from app.config import load_settings
from app.ig import types as t
from app.ig.graph import GraphAdapter

pytestmark = pytest.mark.skipif(
    not os.environ.get("IG_GRAPH_TOKEN"),
    reason="IG_GRAPH_TOKEN not set; live canary is opt-in",
)

TARGET = os.environ.get("IG_CANARY_TARGET", "nike")


@pytest.fixture
def adapter():
    return GraphAdapter(load_settings())


def test_token_is_accepted(adapter):
    adapter.login()


def test_profile_has_the_shape_we_map(adapter):
    profile = adapter.fetch_profile(TARGET)
    assert profile.username.lower() == TARGET.lower()
    assert profile.user_id
    assert profile.post_count >= 0
    assert profile.avatar_url.startswith("https://")
    assert profile.is_private is False


def test_first_page_yields_posts_with_sources(adapter):
    page = adapter.fetch_page(TARGET, None, 3)
    assert page.posts, "a public business account should have posts"
    for post in page.posts:
        assert post.shortcode
        assert post.ig_url.startswith("https://")
        assert post.thumb_url.startswith("https://")
        assert post.sources, "every post must carry at least one downloadable source"
        assert post.kind in {"image", "video", "reel", "carousel"}


def test_a_personal_account_is_reported_as_out_of_scope(adapter):
    """Pins the one error mapping the spec left unconfirmed.

    Set IG_CANARY_PERSONAL to a known public *personal* account. If this
    fails, read the message it reports and correct the hint lists in
    app/ig/graph.py rather than loosening this assertion.
    """
    personal = os.environ.get("IG_CANARY_PERSONAL")
    if not personal:
        pytest.skip("IG_CANARY_PERSONAL not set")
    with pytest.raises((t.IgPrivate, t.IgNotFound)) as caught:
        adapter.fetch_profile(personal)
    assert isinstance(caught.value, t.IgPrivate), (
        f"expected IgPrivate for a personal account, got {type(caught.value).__name__}: "
        f"{caught.value}"
    )
