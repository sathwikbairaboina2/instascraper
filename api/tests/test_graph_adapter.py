import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.ig import types as t
from app.ig.graph import GraphAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "graph"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class Transport:
    """Records every request and replays queued responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []
        self.headers = []

    def __call__(self, url, headers):
        self.urls.append(url)
        self.headers.append(headers)
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        return self.responses.pop(0)


@pytest.fixture
def graph_settings(settings):
    return replace(
        settings,
        adapter="graph",
        graph_token="TOK",
        graph_user_id="SELF",
        graph_version="v99.0",
        graph_refresh_pages=2,
        graph_usage_limit=90.0,
    )


def test_fetch_profile_maps_the_response(graph_settings):
    transport = Transport((200, {}, load("profile.json")))
    adapter = GraphAdapter(graph_settings, transport=transport)

    profile = adapter.fetch_profile("nike")

    assert profile.username == "nike"
    assert profile.post_count == 1669


def test_token_travels_in_a_header_and_never_in_the_url(graph_settings):
    transport = Transport((200, {}, load("profile.json")))
    GraphAdapter(graph_settings, transport=transport).fetch_profile("nike")

    assert "TOK" not in transport.urls[0]
    assert "access_token" not in transport.urls[0]
    assert transport.headers[0]["Authorization"] == "Bearer TOK"


def test_request_targets_our_own_node_and_the_pinned_version(graph_settings):
    transport = Transport((200, {}, load("profile.json")))
    GraphAdapter(graph_settings, transport=transport).fetch_profile("nike")

    url = transport.urls[0]
    assert "/v99.0/SELF" in url
    assert "business_discovery.username(nike)" in url


def test_meta_error_is_classified(graph_settings):
    body = {"error": {"code": 190, "message": "expired"}}
    transport = Transport((400, {}, body))
    adapter = GraphAdapter(graph_settings, transport=transport)

    with pytest.raises(t.IgChallenge):
        adapter.fetch_profile("nike")


def test_saturated_usage_stops_spending_before_the_call(graph_settings):
    """The first call reports 95% usage; the second must not be made."""
    transport = Transport(
        (200, {"x-app-usage": '{"call_count":95}'}, load("profile.json")),
        (200, {}, load("profile.json")),
    )
    adapter = GraphAdapter(graph_settings, transport=transport)
    adapter.fetch_profile("nike")

    with pytest.raises(t.IgRateLimited):
        adapter.fetch_profile("nike")
    assert len(transport.urls) == 1


def test_login_validates_the_token(graph_settings):
    transport = Transport((200, {}, {"id": "SELF"}))
    GraphAdapter(graph_settings, transport=transport).login()
    assert len(transport.urls) == 1


def test_login_surfaces_a_dead_token_as_a_challenge(graph_settings):
    transport = Transport((400, {}, {"error": {"code": 190, "message": "bad"}}))
    with pytest.raises(t.IgChallenge):
        GraphAdapter(graph_settings, transport=transport).login()


def test_missing_token_is_a_challenge_not_a_crash(settings):
    bare = replace(
        settings,
        adapter="graph",
        graph_token="",
        graph_user_id="",
        graph_version="v99.0",
        graph_refresh_pages=2,
        graph_usage_limit=90.0,
    )
    with pytest.raises(t.IgChallenge):
        GraphAdapter(bare).login()


def test_fetch_page_maps_posts_and_the_cursor(graph_settings):
    transport = Transport((200, {}, load("media_page.json")))
    page = GraphAdapter(graph_settings, transport=transport).fetch_page("nike", None, 3)

    assert [p.shortcode for p in page.posts] == [
        "AAAAAAAAAAA",
        "BBBBBBBBBBB",
        "CCCCCCCCCCC",
    ]
    assert page.next_cursor == "CURSOR_AFTER_1"


def test_first_page_requests_a_limit_and_no_after(graph_settings):
    transport = Transport((200, {}, load("media_page.json")))
    GraphAdapter(graph_settings, transport=transport).fetch_page("nike", None, 3)

    url = transport.urls[0]
    assert "media.limit(3)" in url
    assert "after(" not in url


def test_later_page_threads_the_cursor_into_after(graph_settings):
    transport = Transport((200, {}, load("media_page.json")))
    GraphAdapter(graph_settings, transport=transport).fetch_page("nike", "CURSOR_AFTER_1", 36)

    url = transport.urls[0]
    assert "media.limit(36).after(CURSOR_AFTER_1)" in url


def test_exhausted_page_reports_no_cursor(graph_settings):
    transport = Transport((200, {}, load("media_last_page.json")))
    page = GraphAdapter(graph_settings, transport=transport).fetch_page("nike", "c", 36)
    assert page.next_cursor is None
