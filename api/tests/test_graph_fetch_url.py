from pathlib import Path

import pytest

from app.ig import types as t
from app.ig.graph import GraphAdapter


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
