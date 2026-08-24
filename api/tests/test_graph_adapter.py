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
    """An empty page ends the walk even though Meta still hands back a cursor."""
    transport = Transport((200, {}, load("media_last_page.json")))
    page = GraphAdapter(graph_settings, transport=transport).fetch_page("nike", "c", 36)
    assert page.next_cursor is None


def test_a_full_page_pages_on_without_a_next_link(graph_settings):
    """The nested media edge never sends `paging.next`.

    Business Discovery returns `paging.cursors.after` alone, so keying the
    walk on `next` marked every profile exhausted after its first page.
    """
    transport = Transport((200, {}, load("media_page.json")))
    page = GraphAdapter(graph_settings, transport=transport).fetch_page("nike", None, 36)
    assert page.posts
    assert page.next_cursor == "CURSOR_AFTER_1"


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


def test_factory_returns_a_graph_adapter_by_default(graph_settings):
    from app.ig.factory import make_adapter

    assert isinstance(make_adapter(graph_settings), GraphAdapter)


def test_factory_still_serves_the_seeded_fake_for_tests(settings):
    from app.ig.factory import make_adapter
    from app.ig.fake import FakeAdapter

    adapter = make_adapter(settings)  # settings.adapter == "fake"
    assert isinstance(adapter, FakeAdapter)
    assert "nike" in adapter.profiles


def test_graph_settings_are_read_from_the_environment(monkeypatch):
    from app.config import load_settings

    monkeypatch.setenv("IG_GRAPH_TOKEN", "T")
    monkeypatch.setenv("IG_GRAPH_USER_ID", "U")
    monkeypatch.setenv("IG_GRAPH_VERSION", "v99.0")
    monkeypatch.setenv("IG_GRAPH_REFRESH_PAGES", "5")
    monkeypatch.setenv("IG_GRAPH_USAGE_LIMIT", "70")

    loaded = load_settings()

    assert loaded.graph_token == "T"
    assert loaded.graph_user_id == "U"
    assert loaded.graph_version == "v99.0"
    assert loaded.graph_refresh_pages == 5
    assert loaded.graph_usage_limit == 70.0


def test_adapter_defaults_to_graph(monkeypatch):
    from app.config import load_settings

    monkeypatch.delenv("IG_ADAPTER", raising=False)
    assert load_settings().adapter == "graph"


def test_usage_reflects_the_latest_reading_not_the_peak(graph_settings):
    """The hourly window resets; a readout that only climbs would lie."""
    transport = Transport(
        (200, {"x-app-usage": '{"call_count":80}'}, load("media_page.json")),
        (200, {"x-app-usage": '{"call_count":5}'}, load("media_page.json")),
    )
    adapter = GraphAdapter(graph_settings, transport=transport)

    adapter.fetch_page("nike", None, 3)
    assert adapter.usage == 80.0

    adapter.fetch_page("nike", "c", 3)
    assert adapter.usage == 5.0
    assert adapter.usage_peak == 80.0


def test_the_backoff_guard_still_reads_the_peak(graph_settings):
    """A dropped reading must not hand back a call we already refused."""
    transport = Transport(
        (200, {"x-app-usage": '{"call_count":95}'}, load("media_page.json")),
    )
    adapter = GraphAdapter(graph_settings, transport=transport)
    adapter.fetch_page("nike", None, 3)

    with pytest.raises(t.IgRateLimited):
        adapter.fetch_page("nike", "c", 3)


def test_a_reel_reports_that_meta_publishes_no_file_for_it(graph_settings, tmp_path):
    """A reel carries no downloadable url, and saying so is the whole job.

    Left to fall through, the empty source list downloads nothing and marks
    the post ready, or reaches httpx as a malformed url. Neither tells
    anyone that Meta simply does not publish the video.
    """
    reel_page = {
        "business_discovery": {
            "media": {
                "data": [
                    {
                        "id": "1",
                        "caption": "a reel",
                        "media_type": "VIDEO",
                        "media_product_type": "REELS",
                        "thumbnail_url": "https://cdn/t.jpg",
                        "permalink": "https://www.instagram.com/reel/REELCODE123/",
                        "timestamp": "2026-08-20T14:03:11+0000",
                    }
                ],
                "paging": {"cursors": {"after": "C1"}},
            }
        },
        "id": "SELF",
    }
    transport = Transport((200, {}, reel_page))
    adapter = GraphAdapter(graph_settings, transport=transport, fetcher=Fetcher({}))
    hint = t.MediaHint(username="nike", sources=(), captured_at="")

    with pytest.raises(t.IgNotFound) as caught:
        adapter.fetch_media("REELCODE123", tmp_path, hint)

    assert "reel" in str(caught.value).lower()


def test_a_source_with_no_url_never_reaches_the_fetcher(graph_settings, tmp_path):
    """Rows indexed before reels were understood still carry an empty url.

    The hint comes from our database, not from Meta. Handed on, httpx calls
    the empty string a malformed request and the adapter wraps that as
    transient -- so the job retries three times before failing with a
    message about a protocol prefix.
    """
    reel_page = {
        "business_discovery": {
            "media": {
                "data": [
                    {
                        "id": "1",
                        "media_type": "VIDEO",
                        "media_product_type": "REELS",
                        "thumbnail_url": "https://cdn/t.jpg",
                        "permalink": "https://www.instagram.com/reel/REELCODE123/",
                        "timestamp": "2026-08-20T14:03:11+0000",
                    }
                ],
                "paging": {"cursors": {"after": "C1"}},
            }
        },
        "id": "SELF",
    }

    asked: list[str] = []

    def fetcher(url: str):
        asked.append(url)
        return 200, b"DATA"

    stale = t.MediaHint(
        username="nike",
        sources=(t.MediaSource(child_idx=0, url="", mime="video/mp4", is_video=True),),
        captured_at="",
    )
    adapter = GraphAdapter(
        graph_settings, transport=Transport((200, {}, reel_page)), fetcher=fetcher
    )

    with pytest.raises(t.IgNotFound) as caught:
        adapter.fetch_media("REELCODE123", tmp_path, stale)

    assert asked == [], f"downloaded from a urlless source: {asked}"
    assert "reel" in str(caught.value).lower()


class FakeReels:
    def __init__(self, saved=None, raises=None):
        self.saved, self.raises, self.calls = saved, raises, []

    def download(self, shortcode, dest):
        self.calls.append((shortcode, dest))
        if self.raises:
            raise self.raises
        return self.saved


def _reel_page():
    return {
        "business_discovery": {
            "media": {
                "data": [
                    {
                        "id": "1",
                        "media_type": "VIDEO",
                        "media_product_type": "REELS",
                        "thumbnail_url": "https://cdn/t.jpg",
                        "permalink": "https://www.instagram.com/reel/REELCODE123/",
                        "timestamp": "2026-08-20T14:03:11+0000",
                    }
                ],
                "paging": {"cursors": {"after": "C1"}},
            }
        },
        "id": "SELF",
    }


def test_a_reel_falls_back_to_the_downloader(graph_settings, tmp_path):
    saved = t.SavedFile(
        child_idx=0, path=tmp_path / "full.mp4", mime="video/mp4", bytes=7,
        width=None, height=None,
    )
    reels = FakeReels(saved=saved)
    adapter = GraphAdapter(
        graph_settings,
        transport=Transport((200, {}, _reel_page())),
        fetcher=Fetcher({}),
        reel_downloader=reels,
    )
    hint = t.MediaHint(username="nike", sources=(), captured_at="")

    result = adapter.fetch_media("REELCODE123", tmp_path, hint)

    assert result == [saved]
    assert reels.calls[0][0] == "REELCODE123"


def test_the_downloader_is_never_asked_when_graph_has_a_url(graph_settings, tmp_path):
    """The fallback exists for what Graph cannot serve, and nothing else."""
    reels = FakeReels()
    adapter = GraphAdapter(
        graph_settings,
        transport=Transport(),
        fetcher=Fetcher({"https://cdn/i.jpg": b"IMG"}),
        reel_downloader=reels,
    )
    hint = t.MediaHint(
        username="nike",
        sources=(t.MediaSource(0, "https://cdn/i.jpg", "image/jpeg", False),),
        captured_at="",
    )

    adapter.fetch_media("AAAAAAAAAAA", tmp_path, hint)

    assert reels.calls == []


def test_without_a_downloader_a_reel_still_explains_itself(graph_settings, tmp_path):
    adapter = GraphAdapter(
        graph_settings,
        transport=Transport((200, {}, _reel_page())),
        fetcher=Fetcher({}),
    )
    hint = t.MediaHint(username="nike", sources=(), captured_at="")

    with pytest.raises(t.IgNotFound) as caught:
        adapter.fetch_media("REELCODE123", tmp_path, hint)

    assert "reel" in str(caught.value).lower()
