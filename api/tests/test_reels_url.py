import json
from pathlib import Path

import pytest

from app.ig import types as t
from app.ig.reels import ReelDownloader, classify_failure

INFO = {
    "id": "C8yQvW2xyz",
    "uploader_id": "travelgram",
    "description": "golden hour",
    "timestamp": 1755772800,
    "thumbnail": "https://cdn.test/thumb.jpg",
    "like_count": 12400,
    "comment_count": 213,
    "view_count": 98000,
}


class Runner:
    def __init__(self, code=0, stdout=None, stderr="", writes: bytes | None = b"MP4"):
        self.code = code
        self.stdout = json.dumps(INFO) if stdout is None else stdout
        self.stderr, self.writes = stderr, writes
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if self.writes is not None:
            Path(argv[argv.index("-o") + 1]).write_bytes(self.writes)
        return self.code, self.stdout, self.stderr


def test_the_pasted_url_is_used_verbatim(settings, tmp_path):
    runner = Runner()
    ReelDownloader(settings, runner=runner, spend=lambda: None).download_url(
        "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path / "full.mp4"
    )

    argv = runner.calls[0][0]
    assert argv[-1] == "https://www.instagram.com/reel/C8yQvW2xyz/"


def test_one_process_downloads_and_reports_metadata(settings, tmp_path):
    """-J with --no-simulate: the metadata rides along with the download."""
    runner = Runner()
    saved, info = ReelDownloader(settings, runner=runner, spend=lambda: None).download_url(
        "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path / "full.mp4"
    )

    argv = runner.calls[0][0]
    assert "-J" in argv and "--no-simulate" in argv
    assert len(runner.calls) == 1
    assert info["uploader_id"] == "travelgram"
    assert saved.mime == "video/mp4"
    assert saved.bytes == 3


def test_unparseable_metadata_is_transient(settings, tmp_path):
    runner = Runner(stdout="not json")
    with pytest.raises(t.IgTransient):
        ReelDownloader(settings, runner=runner, spend=lambda: None).download_url(
            "https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path / "full.mp4"
        )


def test_the_attempt_is_spent_first(settings, tmp_path):
    order: list[str] = []
    inner = Runner(code=1, stderr="ERROR: boom")

    def recording_runner(argv, timeout):
        order.append("run")
        return inner(argv, timeout)

    with pytest.raises(t.IgError):
        ReelDownloader(
            settings, runner=recording_runner, spend=lambda: order.append("spend")
        ).download_url("https://www.instagram.com/reel/C8yQvW2xyz/", tmp_path / "full.mp4")

    assert order == ["spend", "run"]


def test_an_image_post_maps_to_not_found():
    """yt-dlp cannot fetch image posts; the error must be terminal, not retried."""
    err = classify_failure("ERROR: [Instagram] C8x: There is no video in this post")
    assert isinstance(err, t.IgNotFound)
