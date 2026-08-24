from pathlib import Path

import pytest

from app.ig import types as t
from app.ig.reels import ReelDownloader, classify_failure


class Runner:
    """Records argv instead of spawning anything."""

    def __init__(self, code=0, stdout="", stderr="", writes: bytes | None = b"MP4"):
        self.code, self.stdout, self.stderr, self.writes = code, stdout, stderr, writes
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if self.writes is not None:
            # yt-dlp writes the file itself; the fake stands in for that.
            Path(argv[argv.index("-o") + 1]).write_bytes(self.writes)
        return self.code, self.stdout, self.stderr


def test_the_reel_url_is_built_from_the_shortcode(settings, tmp_path):
    runner = Runner()
    ReelDownloader(settings, runner=runner, spend=lambda: None).download(
        "ABC123", tmp_path / "full.mp4"
    )

    argv = runner.calls[0][0]
    assert argv[-1] == "https://www.instagram.com/reel/ABC123/"


def test_no_user_agent_flags_are_passed(settings, tmp_path):
    """Disguise is exposure without protection, and is deliberately absent."""
    runner = Runner()
    ReelDownloader(settings, runner=runner, spend=lambda: None).download(
        "ABC123", tmp_path / "full.mp4"
    )

    argv = " ".join(runner.calls[0][0])
    assert "user-agent" not in argv.lower()


def test_the_timeout_comes_from_settings(settings, tmp_path):
    runner = Runner()
    ReelDownloader(settings, runner=runner, spend=lambda: None).download(
        "ABC123", tmp_path / "full.mp4"
    )

    assert runner.calls[0][1] == settings.reel_timeout


def test_a_saved_file_describes_the_video(settings, tmp_path):
    dest = tmp_path / "full.mp4"
    saved = ReelDownloader(settings, runner=Runner(), spend=lambda: None).download(
        "ABC123", dest
    )

    assert saved.child_idx == 0
    assert saved.mime == "video/mp4"
    assert saved.path == dest
    assert saved.bytes == 3


def test_the_attempt_is_spent_before_the_process_starts(settings, tmp_path):
    """A failed download still sent the requests the cap exists to limit."""
    order: list[str] = []
    runner = Runner(code=1, stderr="ERROR: boom")

    def spend():
        order.append("spend")

    def recording_runner(argv, timeout):
        order.append("run")
        return runner(argv, timeout)

    with pytest.raises(t.IgError):
        ReelDownloader(settings, runner=recording_runner, spend=spend).download(
            "ABC123", tmp_path / "full.mp4"
        )

    assert order == ["spend", "run"]


def test_a_spent_cap_stops_the_process_from_starting(settings, tmp_path):
    runner = Runner()

    def spend():
        raise t.IgQuotaSpent("hourly reel cap spent")

    with pytest.raises(t.IgQuotaSpent):
        ReelDownloader(settings, runner=runner, spend=spend).download(
            "ABC123", tmp_path / "full.mp4"
        )

    assert runner.calls == [], "spawned a process against a spent cap"


def test_a_file_that_never_appeared_is_an_error(settings, tmp_path):
    """A zero exit code is not proof the download happened."""
    runner = Runner(writes=None)

    with pytest.raises(t.IgTransient):
        ReelDownloader(settings, runner=runner, spend=lambda: None).download(
            "ABC123", tmp_path / "full.mp4"
        )


def test_a_timeout_becomes_an_error_rather_than_a_hung_queue(settings, monkeypatch):
    """One worker thread serves the whole app.

    This covers the real subprocess wrapper, which the injected runner in
    every other test deliberately bypasses.
    """
    import subprocess

    from app.ig import reels

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=5)

    monkeypatch.setattr(subprocess, "run", boom)

    with pytest.raises(t.IgTransient) as caught:
        reels._subprocess_runner(["yt-dlp"], 5.0)

    assert "timed out" in str(caught.value)


@pytest.mark.parametrize(
    "stderr, expected",
    [
        ("ERROR: [Instagram] rate-limit reached, try again later", t.IgRateLimited),
        ("ERROR: Requested content is not available, login required", t.IgChallenge),
        ("ERROR: [Instagram] ABC: Post not available", t.IgNotFound),
        ("ERROR: unable to download video data: HTTP Error 500", t.IgTransient),
        ("", t.IgTransient),
    ],
)
def test_stderr_maps_to_a_real_error_type(stderr, expected):
    assert isinstance(classify_failure(stderr), expected)
