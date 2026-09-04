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

    def __call__(self, url, headers):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        return self.responses.pop(0)


class FakeReels:
    def __init__(self, info=None):
        self.info = info or {
            "id": "C8yQvW2xyz",
            # As yt-dlp reports Instagram: channel is the handle, uploader_id
            # the numeric account id, uploader the display name.
            "channel": "travelgram",
            "uploader_id": "16278726",
            "uploader": "Travel Gram",
            "description": "golden hour",
            "timestamp": 1755772800,
            "thumbnail": "https://cdn.test/thumb.jpg",
            "like_count": 12400,
            "comment_count": 213,
            "view_count": 98000,
        }
        self.calls: list[tuple[str, Path]] = []

    def download_url(self, url: str, dest: Path):
        self.calls.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MP4")
        return (
            t.SavedFile(0, dest, "video/mp4", 3, 720, 1280),
            self.info,
        )


def test_fetch_url_lands_the_file_under_the_owner(settings, tmp_path):
    reels = FakeReels()
    adapter = GraphAdapter(settings, reel_downloader=reels)

    username, post, saved = adapter.fetch_url(
        "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path
    )

    assert username == "travelgram"
    assert saved[0].path == tmp_path / "travelgram" / "C8yQvW2xyz" / "full.mp4"
    assert reels.calls[0][0] == "https://www.instagram.com/reel/C8yQvW2xyz/"


def test_fetch_url_builds_the_post_from_the_metadata(settings, tmp_path):
    adapter = GraphAdapter(settings, reel_downloader=FakeReels())

    _, post, _ = adapter.fetch_url(
        "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path
    )

    assert post.shortcode == "C8yQvW2xyz"
    assert post.kind == "reel"
    assert post.is_video is True
    assert post.caption == "golden hour"
    assert post.taken_at_iso.startswith("2025-08-21")
    assert post.like_count == 12400
    assert post.comments_count == 213
    assert post.view_count == 98000
    assert post.thumb_url == "https://cdn.test/thumb.jpg"
    assert post.ig_url == "https://www.instagram.com/reel/C8yQvW2xyz/"


def test_a_post_link_is_a_video_not_a_reel(settings, tmp_path):
    adapter = GraphAdapter(settings, reel_downloader=FakeReels())

    _, post, _ = adapter.fetch_url("https://www.instagram.com/p/C8yQvW2xyz/", tmp_path)

    assert post.kind == "video"


def test_the_handle_is_preferred_over_the_numeric_account_id(settings, tmp_path):
    """uploader_id is numeric for Instagram; only the handle names a profile."""
    reels = FakeReels(
        info={"id": "x", "channel": "travelgram", "uploader_id": "16278726"}
    )
    adapter = GraphAdapter(settings, reel_downloader=reels)

    username, _, _ = adapter.fetch_url(
        "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path
    )

    assert username == "travelgram"


def test_an_unknown_owner_is_an_error_not_a_misfiled_row(settings, tmp_path):
    reels = FakeReels(info={"id": "x"})
    adapter = GraphAdapter(settings, reel_downloader=reels)

    with pytest.raises(t.IgTransient):
        adapter.fetch_url("https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path)


def test_without_a_downloader_the_fetch_refuses(settings, tmp_path):
    adapter = GraphAdapter(settings, reel_downloader=None)

    with pytest.raises(t.IgTransient):
        adapter.fetch_url("https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path)


def test_a_bad_url_is_not_found(settings, tmp_path):
    adapter = GraphAdapter(settings, reel_downloader=FakeReels())

    with pytest.raises(t.IgNotFound):
        adapter.fetch_url("https://example.com/nope", tmp_path)


# ---- image posts, which yt-dlp refuses -------------------------------------


class NoVideoReels:
    """yt-dlp's answer for a post that holds pictures rather than a video."""

    def __init__(self):
        self.calls: list[tuple[str, Path]] = []

    def download_url(self, url: str, dest: Path):
        self.calls.append((url, dest))
        raise t.IgNoVideo("this link is an image post")


class FakeEmbed:
    def __init__(self, username="nike"):
        self.username = username
        self.calls: list[str] = []

    def owner(self, url: str) -> str:
        self.calls.append(url)
        if self.username is None:
            raise t.IgNotFound("no owner on the embed page")
        return self.username


@pytest.fixture
def graph_settings(settings):
    return replace(
        settings,
        adapter="graph",
        graph_token="TOK",
        graph_user_id="SELF",
        graph_refresh_pages=2,
    )


def image_adapter(graph_settings, embed=None, reels=None, pages=None):
    transport = Transport(*(pages if pages is not None else [(200, {}, load("media_page.json"))]))
    return (
        GraphAdapter(
            graph_settings,
            transport=transport,
            fetcher=lambda url: (200, b"JPEGBYTES"),
            reel_downloader=reels or NoVideoReels(),
            embed=embed or FakeEmbed(),
        ),
        transport,
    )


def test_an_image_post_falls_back_to_the_graph(graph_settings, tmp_path):
    """yt-dlp has no video to give, but Business Discovery has the picture."""
    adapter, _ = image_adapter(graph_settings)

    username, post, saved = adapter.fetch_url(
        "https://www.instagram.com/p/AAAAAAAAAAA/?igsi=dzRp", tmp_path
    )

    assert username == "nike"
    assert post.kind == "image"
    assert post.is_video is False
    assert post.caption == "an image"
    assert [f.path for f in saved] == [tmp_path / "nike" / "AAAAAAAAAAA" / "full.jpg"]
    assert saved[0].path.read_bytes() == b"JPEGBYTES"


def test_the_owner_comes_from_the_embed_page(graph_settings, tmp_path):
    """Business Discovery cannot look up a shortcode; it needs the handle."""
    embed = FakeEmbed()
    adapter, _ = image_adapter(graph_settings, embed=embed)

    adapter.fetch_url("https://www.instagram.com/p/AAAAAAAAAAA/", tmp_path)

    assert embed.calls == ["https://www.instagram.com/p/AAAAAAAAAAA/"]


def test_a_carousel_of_pictures_lands_every_child(graph_settings, tmp_path):
    adapter, _ = image_adapter(graph_settings)

    _, post, saved = adapter.fetch_url(
        "https://www.instagram.com/p/CCCCCCCCCCC/", tmp_path
    )

    assert post.kind == "carousel"
    assert post.child_count == 2
    assert [f.path.name for f in saved] == ["full_1.jpg", "full_2.mp4"]


def test_the_pasted_link_is_kept_as_the_posts_url(graph_settings, tmp_path):
    adapter, _ = image_adapter(graph_settings)

    _, post, _ = adapter.fetch_url(
        "https://www.instagram.com/p/AAAAAAAAAAA/?igsi=dzRp", tmp_path
    )

    assert post.ig_url == "https://www.instagram.com/p/AAAAAAAAAAA/?igsi=dzRp"


def test_without_an_embed_lookup_the_original_refusal_stands(graph_settings, tmp_path):
    """No owner, no fallback: say why the fetch failed, do not invent a guess."""
    adapter = GraphAdapter(
        graph_settings, reel_downloader=NoVideoReels(), embed=None
    )

    with pytest.raises(t.IgNoVideo):
        adapter.fetch_url("https://www.instagram.com/p/AAAAAAAAAAA/", tmp_path)


def test_a_post_the_listing_never_reaches_is_not_found(graph_settings, tmp_path):
    adapter, _ = image_adapter(
        graph_settings,
        pages=[
            (200, {}, load("media_page.json")),
            (200, {}, load("media_last_page.json")),
        ],
    )

    with pytest.raises(t.IgNotFound):
        adapter.fetch_url("https://www.instagram.com/p/ZZZZZZZZZZZ/", tmp_path)


def test_a_private_owner_leaves_the_reel_error_in_place(graph_settings, tmp_path):
    """An embed page with no handle says nothing new about why yt-dlp refused."""
    adapter = GraphAdapter(
        graph_settings,
        reel_downloader=NoVideoReels(),
        embed=FakeEmbed(username=None),
    )

    with pytest.raises(t.IgNotFound):
        adapter.fetch_url("https://www.instagram.com/p/AAAAAAAAAAA/", tmp_path)
