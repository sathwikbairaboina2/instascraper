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


class Fetcher:
    """Serves bytes per url; any url not listed is treated as expired."""

    def __init__(self, available):
        self.available = dict(available)
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        if url in self.available:
            return 200, self.available[url]
        return 403, b""


def hint_for(url, username="nike"):
    return t.MediaHint(
        username=username,
        sources=(t.MediaSource(0, url, "image/jpeg", False),),
        captured_at="2026-08-20T00:00:00+00:00",
    )


def test_fetch_media_downloads_from_the_cached_url(graph_settings, tmp_path):
    fetcher = Fetcher({"https://cdn/fresh.jpg": b"IMAGEBYTES"})
    adapter = GraphAdapter(graph_settings, transport=Transport(), fetcher=fetcher)

    saved = adapter.fetch_media("AAAAAAAAAAA", tmp_path, hint_for("https://cdn/fresh.jpg"))

    assert [s.child_idx for s in saved] == [0]
    assert saved[0].path.read_bytes() == b"IMAGEBYTES"
    assert saved[0].mime == "image/jpeg"
    assert list(tmp_path.glob("*.part")) == []


def test_expired_url_triggers_a_refresh_and_succeeds(graph_settings, tmp_path):
    """The cached url 403s; a re-listing supplies a working one."""
    fetcher = Fetcher({"https://scontent.cdninstagram.com/img1.jpg": b"REFRESHED"})
    transport = Transport((200, {}, load("media_page.json")))
    adapter = GraphAdapter(graph_settings, transport=transport, fetcher=fetcher)

    saved = adapter.fetch_media("AAAAAAAAAAA", tmp_path, hint_for("https://cdn/stale.jpg"))

    assert saved[0].path.read_bytes() == b"REFRESHED"
    assert len(transport.urls) == 1


def test_refresh_stops_at_the_configured_page_bound(graph_settings, tmp_path):
    """Two pages allowed, post is on neither: give up rather than page forever."""
    transport = Transport(
        (200, {}, load("media_page.json")),
        (200, {}, load("media_page.json")),
    )
    adapter = GraphAdapter(graph_settings, transport=transport, fetcher=Fetcher({}))

    with pytest.raises(t.IgNotFound):
        adapter.fetch_media("NOTONANYPAGE", tmp_path, hint_for("https://cdn/stale.jpg"))
    assert len(transport.urls) == 2


def test_refresh_stops_early_when_the_profile_is_exhausted(graph_settings, tmp_path):
    transport = Transport((200, {}, load("media_last_page.json")))
    adapter = GraphAdapter(graph_settings, transport=transport, fetcher=Fetcher({}))

    with pytest.raises(t.IgNotFound):
        adapter.fetch_media("MISSING", tmp_path, hint_for("https://cdn/stale.jpg"))
    assert len(transport.urls) == 1


def test_no_hint_means_nothing_can_be_refreshed(graph_settings, tmp_path):
    adapter = GraphAdapter(graph_settings, transport=Transport(), fetcher=Fetcher({}))
    with pytest.raises(t.IgNotFound):
        adapter.fetch_media("AAAAAAAAAAA", tmp_path, None)


def test_carousel_children_are_written_with_one_based_names(graph_settings, tmp_path):
    fetcher = Fetcher({"https://cdn/a.jpg": b"A", "https://cdn/b.mp4": b"B"})
    hint = t.MediaHint(
        username="nike",
        sources=(
            t.MediaSource(1, "https://cdn/a.jpg", "image/jpeg", False),
            t.MediaSource(2, "https://cdn/b.mp4", "video/mp4", True),
        ),
        captured_at="2026-08-20T00:00:00+00:00",
    )
    adapter = GraphAdapter(graph_settings, transport=Transport(), fetcher=fetcher)

    saved = adapter.fetch_media("CCCCCCCCCCC", tmp_path, hint)

    assert [s.child_idx for s in saved] == [1, 2]
    assert (tmp_path / "full_1.jpg").exists()
    assert (tmp_path / "full_2.mp4").exists()


def test_download_to_writes_a_file(graph_settings, tmp_path):
    fetcher = Fetcher({"https://cdn/avatar.jpg": b"AV"})
    adapter = GraphAdapter(graph_settings, transport=Transport(), fetcher=fetcher)

    saved = adapter.download_to("https://cdn/avatar.jpg", tmp_path / "avatar.jpg")

    assert saved.path.read_bytes() == b"AV"
    assert saved.child_idx == 0


def test_download_to_failure_is_transient(graph_settings, tmp_path):
    adapter = GraphAdapter(graph_settings, transport=Transport(), fetcher=Fetcher({}))
    with pytest.raises(t.IgTransient):
        adapter.download_to("https://cdn/gone.jpg", tmp_path / "x.jpg")
