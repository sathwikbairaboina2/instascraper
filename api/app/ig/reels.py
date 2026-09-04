"""Downloads a reel's video, which Business Discovery will not serve.

The only part of this app that fetches from instagram.com rather than from
the Graph API or its CDN. Everything here exists to keep that footprint
small and legible: a hard cap spent before any process starts, a fixed floor
between calls, a timeout, and no attempt to look like anything other than
what it is.

Deliberately absent: user-agent rotation and randomised "human" sleeps.
Instagram fingerprints request patterns and account behaviour rather than
headers, so disguise buys exposure without protection. The honest lever is
doing less, which is what the cap is.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.config import Settings
from app.probe import dimensions
from app.ig import types as t
from app.worker.pacer import Pacer

Runner = Callable[[list[str], float], tuple[int, str, str]]

_URL = "https://www.instagram.com/reel/{shortcode}/"


def _subprocess_runner(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        # One worker thread serves the whole app; a hung process is not a
        # slow download, it is a stalled queue.
        raise t.IgTransient(f"yt-dlp timed out after {timeout:.0f}s") from None
    return done.returncode, done.stdout, done.stderr


def classify_failure(stderr: str) -> t.IgError:
    """Turn yt-dlp's stderr into something the worker can act on.

    One generic failure would make a rate limit, a dead post and a network
    blip all look alike, and they call for opposite responses.
    """
    lowered = (stderr or "").lower()
    if "rate-limit" in lowered or "429" in lowered or "too many requests" in lowered:
        return t.IgRateLimited("Instagram rate-limited the reel download")
    if "login required" in lowered or "log in" in lowered or "sign in" in lowered:
        return t.IgChallenge("Instagram now requires a login for this reel")
    if "not available" in lowered or "unavailable" in lowered or "removed" in lowered:
        return t.IgNotFound("the reel is no longer available")
    if "no video" in lowered:
        # An image post. yt-dlp only serves video, so retrying it cannot
        # change the answer -- but the Graph API can still have the pictures,
        # which is what the distinct type lets the adapter go and find out.
        return t.IgNoVideo("this link is an image post, which yt-dlp cannot download")
    detail = (stderr or "").strip().splitlines()[-1] if (stderr or "").strip() else "no output"
    return t.IgTransient(f"yt-dlp failed: {detail}")


class ReelDownloader:
    def __init__(
        self,
        settings: Settings,
        runner: Runner | None = None,
        pacer: Pacer | None = None,
        spend: Callable[[], None] | None = None,
    ):
        self._settings = settings
        self._runner = runner or _subprocess_runner
        self._pacer = pacer or Pacer(min_interval=settings.reel_min_interval)
        # Injected rather than reached for: adapters have no database access,
        # and this is the one thing that spends the ledger.
        self._spend = spend or (lambda: None)

    def download_url(self, url: str, dest: Path) -> tuple[t.SavedFile, dict]:
        """Download a pasted link and return its metadata alongside the file.

        One process for both: `-J --no-simulate` makes yt-dlp download while
        printing the info JSON, so a direct fetch costs a single request
        instead of a probe followed by a download.
        """
        self._spend()
        self._pacer.wait()

        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-warnings",
            "--no-playlist",
            "--no-progress",
            "-J",
            "--no-simulate",
            "-f",
            "mp4/best[ext=mp4]/best",
            "-o",
            str(dest),
            url,
        ]
        code, stdout, stderr = self._runner(argv, self._settings.reel_timeout)
        if code != 0:
            raise classify_failure(stderr)
        if not dest.exists():
            raise t.IgTransient("yt-dlp reported success but wrote no file")
        try:
            info = json.loads(stdout)
        except (TypeError, ValueError):
            raise t.IgTransient("yt-dlp wrote the file but its metadata was unreadable") from None

        width, height = dimensions(dest) or (None, None)
        saved = t.SavedFile(
            child_idx=0,
            path=dest,
            mime="video/mp4",
            bytes=dest.stat().st_size,
            width=width,
            height=height,
        )
        return saved, info

    def download(self, shortcode: str, dest: Path) -> t.SavedFile:
        # Spent first. A failed download still sent the requests the cap
        # exists to limit, so recording only successes would understate the
        # footprint exactly when it matters most.
        self._spend()
        self._pacer.wait()

        dest.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-warnings",
            "--no-playlist",
            "--no-progress",
            "-f",
            "mp4/best[ext=mp4]/best",
            "-o",
            str(dest),
            _URL.format(shortcode=shortcode),
        ]
        code, _stdout, stderr = self._runner(argv, self._settings.reel_timeout)
        if code != 0:
            raise classify_failure(stderr)
        if not dest.exists():
            # yt-dlp can exit cleanly having written nothing, and a caller
            # that trusted the exit code would record a ready file that is
            # not there.
            raise t.IgTransient("yt-dlp reported success but wrote no file")

        width, height = dimensions(dest) or (None, None)
        return t.SavedFile(
            child_idx=0,
            path=dest,
            mime="video/mp4",
            bytes=dest.stat().st_size,
            width=width,
            height=height,
        )
