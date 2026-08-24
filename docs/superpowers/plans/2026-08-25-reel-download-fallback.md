# Reel Download Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download reel videos through yt-dlp, which Business Discovery refuses to serve, under a hard local cap of 20 an hour and 100 a day shown as progress in the header.

**Architecture:** A quota ledger in SQLite answers "may I" and "when does headroom return"; a subprocess downloader is the only thing that spends it; `GraphAdapter` delegates to that downloader exactly where a refresh confirms Meta published no file. The downloaded reel lands as `full.mp4` with a `media_files` row, identical to a Graph download, so every downstream feature works unchanged.

**Tech Stack:** FastAPI + SQLite (api), yt-dlp 2026.08.19 invoked via `sys.executable -m yt_dlp`, Next.js 15 + React 19 + antd 6 (web), pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-reel-download-fallback-design.md`

## Global Constraints

- Backend suite: `cd api && ../.venv/Scripts/python.exe -m pytest -q`. Green before every commit.
- e2e suite: `bash scripts/e2e-native.sh` from the repo root. Runs the **fake** adapter.
- **No test may invoke yt-dlp or touch the network.** Every subprocess call goes through an injected runner.
- Caps: 20 per rolling hour (`IG_REEL_MAX_PER_HOUR`), 100 per rolling day (`IG_REEL_MAX_PER_DAY`). Both env-overridable.
- Attempts count, not successes. One place records; callers check but never record.
- No `--random-user-agent`, no randomised sleeps. Fixed interval only.
- ffmpeg is **not** a dependency — reels arrive pre-muxed.
- Adapters have no database access. Quota reaches the downloader as an injected callable.
- Bar colours: under 50% `#2ecc71`, 50–84% `#fcb045`, 85%+ `#ed4956`.
- Commit after every task, conventional prefixes.

---

### Task 1: The quota ledger

Pure window arithmetic over a table, with an injected clock so tests never sleep.

**Files:**
- Create: `api/app/services/quota.py`
- Modify: `api/app/schema.sql`
- Test: `api/tests/test_quota.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `REEL = "reel_download"` (the `kind` value)
  - `record(conn, kind: str, now: str) -> None`
  - `count(conn, kind: str, since: str) -> int`
  - `window(conn, kind: str, seconds: int, limit: int, now: str) -> dict` returning `{"used": int, "max": int, "resets_at": str | None}`. `resets_at` is None when nothing is in the window.
  - `iso_minus(now: str, seconds: int) -> str`
  - All timestamps are ISO-8601 strings, matching `app.clock.now_iso()`.

- [ ] **Step 1: Add the table**

In `api/app/schema.sql`, append:

```sql
CREATE TABLE IF NOT EXISTS quota_events (
  id    INTEGER PRIMARY KEY,
  kind  TEXT NOT NULL,
  at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS quota_events_kind_at ON quota_events(kind, at);
```

The index matters: every check is a range scan on `(kind, at)`.

- [ ] **Step 2: Write the failing tests**

Create `api/tests/test_quota.py`:

```python
from app.services import quota


def test_counts_only_events_inside_the_window(conn):
    quota.record(conn, quota.REEL, "2026-08-25T10:00:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T10:30:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T11:30:00+00:00")

    now = "2026-08-25T11:45:00+00:00"
    result = quota.window(conn, quota.REEL, 3600, 20, now)

    # Only 11:30 is inside the last hour.
    assert result["used"] == 1
    assert result["max"] == 20


def test_an_event_exactly_on_the_window_edge_has_aged_out(conn):
    """The window is half-open: an hour old is out, not in."""
    quota.record(conn, quota.REEL, "2026-08-25T10:00:00+00:00")

    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:00:00+00:00")

    assert result["used"] == 0


def test_reset_is_when_the_oldest_event_in_the_window_ages_out(conn):
    quota.record(conn, quota.REEL, "2026-08-25T11:10:00+00:00")
    quota.record(conn, quota.REEL, "2026-08-25T11:40:00+00:00")

    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")

    # Headroom returns when 11:10 leaves the window, not when 11:40 does.
    assert result["resets_at"] == "2026-08-25T12:10:00+00:00"


def test_an_empty_window_has_nothing_to_reset(conn):
    result = quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")

    assert result == {"used": 0, "max": 20, "resets_at": None}


def test_kinds_do_not_share_a_budget(conn):
    quota.record(conn, "something_else", "2026-08-25T11:40:00+00:00")

    assert quota.window(conn, quota.REEL, 3600, 20, "2026-08-25T11:45:00+00:00")["used"] == 0
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_quota.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.quota'`.

- [ ] **Step 4: Implement**

Create `api/app/services/quota.py`:

```python
"""What we have spent against our own limits, and when that frees up.

Not Instagram's accounting -- ours. Because we own the ledger, the reset
time is exact rather than estimated, which is the whole reason the header
can show a countdown here and cannot for Meta's quota.
"""

import sqlite3
from datetime import datetime, timedelta

REEL = "reel_download"

# Old rows are worth keeping briefly -- they answer "what did this thing do
# last night" -- but nothing reads past the widest window.
_KEEP_SECONDS = 7 * 86400


def iso_minus(now: str, seconds: int) -> str:
    return (datetime.fromisoformat(now) - timedelta(seconds=seconds)).isoformat()


def record(conn: sqlite3.Connection, kind: str, now: str) -> None:
    conn.execute("INSERT INTO quota_events (kind, at) VALUES (?,?)", (kind, now))
    conn.execute(
        "DELETE FROM quota_events WHERE at <= ?", (iso_minus(now, _KEEP_SECONDS),)
    )


def count(conn: sqlite3.Connection, kind: str, since: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM quota_events WHERE kind=? AND at > ?", (kind, since)
    ).fetchone()["c"]


def window(
    conn: sqlite3.Connection, kind: str, seconds: int, limit: int, now: str
) -> dict:
    """Usage inside one rolling window, and when the oldest entry leaves it."""
    since = iso_minus(now, seconds)
    row = conn.execute(
        "SELECT COUNT(*) c, MIN(at) oldest FROM quota_events"
        " WHERE kind=? AND at > ?",
        (kind, since),
    ).fetchone()
    oldest = row["oldest"]
    resets_at = (
        (datetime.fromisoformat(oldest) + timedelta(seconds=seconds)).isoformat()
        if oldest
        else None
    )
    return {"used": row["c"], "max": limit, "resets_at": resets_at}
```

Note `at > ?` rather than `>=`: an event exactly one window old has aged out.

- [ ] **Step 5: Run to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_quota.py -q`
Expected: PASS.

- [ ] **Step 6: Add the settings**

In `api/app/config.py`, add to the `Settings` dataclass after `graph_usage_limit`:

```python
    reel_max_per_hour: int
    reel_max_per_day: int
    reel_timeout: float
    reel_min_interval: float
```

and in `load_settings`:

```python
        # Our own caps on scraping instagram.com for reel video, which the
        # Graph API will not serve. Conservative rather than authoritative:
        # Instagram publishes no thresholds.
        reel_max_per_hour=int(os.environ.get("IG_REEL_MAX_PER_HOUR", "20")),
        reel_max_per_day=int(os.environ.get("IG_REEL_MAX_PER_DAY", "100")),
        reel_timeout=float(os.environ.get("IG_REEL_TIMEOUT", "120")),
        reel_min_interval=float(os.environ.get("IG_REEL_MIN_INTERVAL", "20")),
```

In `api/tests/conftest.py`, add to the `settings` fixture so every test keeps constructing:

```python
        reel_max_per_hour=20,
        reel_max_per_day=100,
        reel_timeout=5.0,
        reel_min_interval=0.0,
```

- [ ] **Step 7: Run the full suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/app/services/quota.py api/app/schema.sql api/app/config.py api/tests
git commit -m "feat(api): add a quota ledger for our own scraping limits"
```

---

### Task 2: `IgQuotaSpent` and the worker branch

A spent local cap must fail the job without backing off the Graph API.

**Files:**
- Modify: `api/app/ig/types.py`
- Modify: `api/app/worker/runner.py:110-135`
- Test: `api/tests/test_worker_runner.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `t.IgQuotaSpent(message: str, resets_at: str | None = None)`, a subclass of `IgError`. The worker fails its job non-retryably and does **not** touch the breaker.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_worker_runner.py`:

```python
def test_a_spent_local_cap_fails_the_job_without_tripping_the_breaker(worker_env):
    """Our own limit is not Instagram refusing us.

    Tripping the breaker here would stop Graph API work too, which has its
    own quota and is nowhere near it.
    """
    settings, conn, adapter, breaker, pacer = worker_env

    def handler(ctx, payload):
        raise t.IgQuotaSpent("hourly reel cap spent", resets_at="2026-08-25T12:10:00+00:00")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT status, error FROM jobs").fetchone()
    assert row["status"] == "failed"
    assert "cap spent" in row["error"]
    assert breaker.state()["tripped"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_worker_runner.py -q`
Expected: FAIL — `AttributeError: module 'app.ig.types' has no attribute 'IgQuotaSpent'`.

- [ ] **Step 3: Add the type**

In `api/app/ig/types.py`, after `IgChallenge`:

```python
class IgQuotaSpent(IgError):
    """Our own cap, not Instagram's.

    Terminal for this job and invisible to the breaker: backing off the
    Graph API because a local scraping budget ran out would punish the one
    path that is behaving.
    """

    def __init__(self, message: str, resets_at: str | None = None):
        super().__init__(message)
        self.resets_at = resets_at
```

- [ ] **Step 4: Handle it in the worker**

In `api/app/worker/runner.py`, add a branch **before** the `IgNotFound`/`IgPrivate` one:

```python
        except t.IgQuotaSpent as exc:
            queue.fail(conn, job["id"], str(exc), retryable=False)
            self._log(job, payload, started, "quota_spent")
            return
```

- [ ] **Step 5: Run the full suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/ig/types.py api/app/worker/runner.py api/tests/test_worker_runner.py
git commit -m "feat(api): fail a job on a spent local cap without tripping the breaker"
```

---

### Task 3: The reel downloader

**Files:**
- Create: `api/app/ig/reels.py`
- Test: `api/tests/test_reels.py` (create)

**Interfaces:**
- Consumes: `t.IgQuotaSpent` from Task 2.
- Produces:
  - `ReelDownloader(settings, runner=None, pacer=None, spend=None)`
  - `spend: Callable[[], None]` — raises `t.IgQuotaSpent` when the cap is gone, otherwise records the attempt. Injected; the downloader never touches SQLite.
  - `runner: Callable[[list[str], float], tuple[int, str, str]]` — argv and timeout in, `(returncode, stdout, stderr)` out.
  - `download(shortcode: str, dest: Path) -> t.SavedFile` with `child_idx=0`, `mime="video/mp4"`, `is_video=True`.
  - `classify_failure(stderr: str) -> t.IgError` (module-level, so its mapping is testable alone).

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_reels.py`:

```python
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
    assert saved.is_video is True
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_reels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ig.reels'`.

- [ ] **Step 3: Implement**

Create `api/app/ig/reels.py`:

```python
"""Downloads a reel's video, which Business Discovery will not serve.

The only part of this app that fetches from instagram.com rather than from
the Graph API or its CDN. Everything here exists to keep that footprint
small and legible: a hard cap spent before any process starts, a fixed floor
between calls, a timeout, and no attempt to look like anything other than
what it is.
"""

import subprocess
import sys
from pathlib import Path
from typing import Callable

from app import paths
from app.config import Settings
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
    """Turn yt-dlp's stderr into something the worker can act on."""
    lowered = (stderr or "").lower()
    if "rate-limit" in lowered or "429" in lowered or "too many requests" in lowered:
        return t.IgRateLimited("Instagram rate-limited the reel download")
    if "login required" in lowered or "log in" in lowered or "sign in" in lowered:
        return t.IgChallenge("Instagram now requires a login for this reel")
    if "not available" in lowered or "unavailable" in lowered or "removed" in lowered:
        return t.IgNotFound("the reel is no longer available")
    detail = (stderr or "").strip().splitlines()[-1] if stderr.strip() else "no output"
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

    def download(self, shortcode: str, dest: Path) -> t.SavedFile:
        # Spent first. A failed download still sent the requests the cap
        # exists to limit, so recording only successes would understate the
        # footprint exactly when it matters.
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
            raise t.IgTransient("yt-dlp reported success but wrote no file")

        return t.SavedFile(
            child_idx=0,
            path=dest,
            mime="video/mp4",
            bytes=dest.stat().st_size,
            width=None,
            height=None,
        )
```

If `SavedFile` does not accept these keywords, read `api/app/ig/types.py` and match its actual field names — do not change the dataclass.

- [ ] **Step 4: Run to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_reels.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`

```bash
git add api/app/ig/reels.py api/tests/test_reels.py
git commit -m "feat(api): download reel video through yt-dlp under an injected cap"
```

---

### Task 4: The adapter falls back

**Files:**
- Modify: `api/app/ig/graph.py` (`fetch_media`, `_refresh`, `__init__`)
- Modify: `api/app/ig/factory.py`
- Test: `api/tests/test_graph_adapter.py`

**Interfaces:**
- Consumes: `ReelDownloader.download` from Task 3.
- Produces: `GraphAdapter(settings, transport=None, fetcher=None, reel_downloader=None)`. When Graph has no url and a downloader is present, `fetch_media` returns `[SavedFile]` from it. With no downloader it raises the existing "Meta publishes no downloadable file" `IgNotFound`.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_graph_adapter.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_adapter.py -q`
Expected: FAIL — `GraphAdapter.__init__() got an unexpected keyword argument 'reel_downloader'`.

- [ ] **Step 3: Move the "no file" decision out of `_refresh`**

In `api/app/ig/graph.py`, `_refresh` currently raises when it finds the post carrying no sources. Replace that raise with a plain return so the caller decides:

```python
            for post in page.posts:
                if post.shortcode == shortcode:
                    # Found. Empty means Meta published no file for it --
                    # which is a fallback opportunity, not an error, so the
                    # judgement belongs to the caller.
                    return post.sources
```

- [ ] **Step 4: Accept the collaborator and use it**

In `__init__`, add the parameter and store it:

```python
    def __init__(self, settings, transport=None, fetcher=None, reel_downloader=None):
        ...
        self._reels = reel_downloader
```

In `fetch_media`, after the refresh:

```python
        sources = tuple(s for s in hint.sources if s.url) if hint else ()
        if not sources:
            sources = self._refresh(shortcode, hint)
        if not sources:
            if self._reels is not None:
                # Business Discovery publishes a thumbnail for a reel and
                # keeps the video. This is the only path in the app that
                # asks instagram.com directly, and only for that gap.
                return [self._reels.download(shortcode, dest_dir / "full.mp4")]
            raise t.IgNotFound(
                f"Meta publishes no downloadable file for {shortcode}: "
                "Business Discovery returns only a thumbnail for a reel, "
                "never the video itself"
            )
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_adapter.py -q`
Expected: PASS.

- [ ] **Step 6: Wire the real thing together**

In `api/app/ig/factory.py`, build the downloader with a `spend` bound to the database:

```python
def make_adapter(settings: Settings):
    if settings.adapter == "fake":
        from app.ig.fake import seeded_adapter

        return seeded_adapter()

    from app.ig.graph import GraphAdapter
    from app.ig.reels import ReelDownloader

    return GraphAdapter(settings, reel_downloader=ReelDownloader(settings, spend=_spend(settings)))


def _spend(settings: Settings):
    """Check both caps and record the attempt, in one indivisible step.

    Bound here rather than inside the downloader because adapters have no
    database access -- the hint mechanism exists for exactly that reason.
    """

    def spend() -> None:
        from app import db
        from app.clock import now_iso
        from app.ig import types as t
        from app.services import quota

        conn = db.get_conn(settings)
        now = now_iso()
        for seconds, limit, label in (
            (3600, settings.reel_max_per_hour, "hourly"),
            (86400, settings.reel_max_per_day, "daily"),
        ):
            state = quota.window(conn, quota.REEL, seconds, limit, now)
            if state["used"] >= limit:
                raise t.IgQuotaSpent(
                    f"{label} reel cap spent ({state['used']}/{limit})",
                    resets_at=state["resets_at"],
                )
        quota.record(conn, quota.REEL, now)

    return spend
```

- [ ] **Step 7: Run the full suite and commit**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

```bash
git add api/app/ig api/tests/test_graph_adapter.py
git commit -m "feat(api): fall back to yt-dlp where Graph publishes no reel file"
```

---

### Task 5: Report the limits and refuse at the cap

**Files:**
- Modify: `api/app/routes/status.py`
- Modify: `api/app/routes/media.py` (`ensure`)
- Test: `api/tests/test_api_status.py`, `api/tests/test_api_media.py`

**Interfaces:**
- Consumes: `quota.window` from Task 1.
- Produces:
  - `GET /api/status` gains `"reel_limits": {"hour": {...}, "day": {...}}`, each `{"used", "max", "resets_at"}`.
  - `POST /api/media/ensure` returns status `"quota"` for an uncached reel when a cap is spent, with the reason in `errors[shortcode]`, and does **not** enqueue.

- [ ] **Step 1: Write the failing status test**

Add to `api/tests/test_api_status.py`:

```python
def test_status_reports_both_reel_windows(client):
    body = client.get("/api/status").json()

    assert body["reel_limits"]["hour"]["max"] == 20
    assert body["reel_limits"]["day"]["max"] == 100
    assert body["reel_limits"]["hour"]["used"] == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_status.py -q`
Expected: FAIL with `KeyError: 'reel_limits'`.

- [ ] **Step 3: Implement**

In `api/app/routes/status.py`, add the import `from app.clock import now_iso` and `from app.services import quota`, then inside `get_status` before the return:

```python
    now = now_iso()
    settings = current.settings
    reel_limits = {
        "hour": quota.window(conn, quota.REEL, 3600, settings.reel_max_per_hour, now),
        "day": quota.window(conn, quota.REEL, 86400, settings.reel_max_per_day, now),
    }
```

and add `"reel_limits": reel_limits,` to the returned dict.

- [ ] **Step 4: Write the failing refusal test**

Add to `api/tests/test_api_media.py`:

```python
def test_ensure_refuses_a_reel_when_the_hourly_cap_is_spent(
    client, conn, settings, adapter
):
    """Refuse where the click happens, rather than queueing a job to die."""
    seed(client, conn, settings, adapter)
    shortcode = conn.execute("SELECT shortcode FROM media_items LIMIT 1").fetchone()[0]
    conn.execute(
        "UPDATE media_items SET kind='reel', full_status='none' WHERE shortcode=?",
        (shortcode,),
    )
    for _ in range(settings.reel_max_per_hour):
        quota.record(conn, quota.REEL, now_iso())

    body = client.post("/api/media/ensure", json={"shortcodes": [shortcode]}).json()

    assert body["statuses"][shortcode] == "quota"
    assert "cap spent" in body["errors"][shortcode]
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0


def test_ensure_still_queues_a_photo_when_the_reel_cap_is_spent(
    client, conn, settings, adapter
):
    """The reel cap governs scraping, not everything the app does."""
    seed(client, conn, settings, adapter)
    shortcode = conn.execute(
        "SELECT shortcode FROM media_items WHERE kind!='reel' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE media_items SET full_status='none' WHERE shortcode=?", (shortcode,)
    )
    for _ in range(settings.reel_max_per_hour):
        quota.record(conn, quota.REEL, now_iso())

    body = client.post("/api/media/ensure", json={"shortcodes": [shortcode]}).json()

    assert body["statuses"][shortcode] == "queued"
```

Add `from app.clock import now_iso` and `from app.services import quota` to that file's imports.

- [ ] **Step 5: Run to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_media.py -q`
Expected: FAIL — the reel is queued rather than refused.

- [ ] **Step 6: Implement the refusal**

In `api/app/routes/media.py`, `ensure` selects `full_status, full_error`; it also needs `kind`. Change the SELECT to `SELECT kind, full_status, full_error FROM media_items WHERE shortcode=?`, and insert this immediately before the `queue.enqueue_unique` call:

```python
        if item["kind"] == "reel":
            settings = request.app.state.runtime.current.settings
            spent = _reel_cap_spent(conn, settings)
            if spent is not None:
                # Refuse where the click happened. A job queued against a
                # spent cap only fails later, somewhere the user is not
                # looking.
                statuses[shortcode] = "quota"
                errors[shortcode] = spent
                continue
```

and add this helper above `ensure`:

```python
def _reel_cap_spent(conn, settings) -> str | None:
    """The reason the next reel cannot be fetched, or None if it can."""
    now = now_iso()
    for seconds, limit, label in (
        (3600, settings.reel_max_per_hour, "hourly"),
        (86400, settings.reel_max_per_day, "daily"),
    ):
        state = quota.window(conn, quota.REEL, seconds, limit, now)
        if state["used"] >= limit:
            return f"{label} reel cap spent ({state['used']}/{limit})"
    return None
```

with imports `from app.clock import now_iso` and `from app.services import quota`.

- [ ] **Step 7: Run the full suite and commit**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

```bash
git add api/app/routes api/tests
git commit -m "feat(api): report the reel caps and refuse at the click"
```

---

### Task 6: Header bars and the refusal on the control

**Files:**
- Modify: `web/lib/api.ts`
- Create: `web/components/ReelLimits.tsx`
- Modify: `web/components/AppShell.tsx`
- Modify: `web/components/SelectionBar.tsx`
- Test: `web/e2e/limits.spec.ts` (create)

**Interfaces:**
- Consumes: `reel_limits` from Task 5; `EnsureResult.statuses` may now contain `"quota"`.
- Produces: `<ReelLimits limits={StatusBody['reel_limits']} />`, test id `reel-limits`, with `reel-limit-hour` and `reel-limit-day` inside.

- [ ] **Step 1: Extend the types**

In `web/lib/api.ts`, add to `StatusBody`:

```ts
  reel_limits: {
    hour: { used: number; max: number; resets_at: string | null }
    day: { used: number; max: number; resets_at: string | null }
  } | null
```

- [ ] **Step 2: Write the component**

Create `web/components/ReelLimits.tsx`:

```tsx
'use client'

import { Flex, Tooltip, Typography } from 'antd'

import type { StatusBody } from '@/lib/api'
import { useThemePref } from './ThemeProvider'

const { Text } = Typography

/** Green while there is room, orange past half, red as it runs out. Flat per
 *  state, never a gradient: a fill whose colour changes along its own length
 *  cannot also encode how full it is. */
function fillFor(ratio: number): string {
  if (ratio >= 0.85) return '#ed4956'
  if (ratio >= 0.5) return '#fcb045'
  return '#2ecc71'
}

function clock(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function Bar({
  label,
  window: w,
  testId,
}: {
  label: string
  window: { used: number; max: number; resets_at: string | null }
  testId: string
}) {
  const { tokens } = useThemePref()
  const ratio = w.max > 0 ? Math.min(w.used / w.max, 1) : 0
  const spent = w.used >= w.max
  const fill = fillFor(ratio)

  return (
    <Tooltip
      title={
        spent
          ? `Reel cap spent. Headroom returns at ${clock(w.resets_at)}.`
          : `${w.used} of ${w.max} reels downloaded this ${label.toLowerCase()}.`
      }
    >
      <Flex vertical gap={2} data-testid={testId} style={{ width: 52 }}>
        <Text
          style={{ fontSize: 9, letterSpacing: '.05em', color: spent ? fill : tokens.textSecondary }}
        >
          {spent ? `${label} · ${clock(w.resets_at)}` : `${label} ${w.used}/${w.max}`}
        </Text>
        <div style={{ height: 3, borderRadius: 999, background: tokens.hairline }}>
          <div
            style={{
              width: `${ratio * 100}%`,
              height: '100%',
              borderRadius: 999,
              background: fill,
            }}
          />
        </div>
      </Flex>
    </Tooltip>
  )
}

export default function ReelLimits({ limits }: { limits: StatusBody['reel_limits'] }) {
  if (!limits) return null
  return (
    <Flex gap={9} align="center" data-testid="reel-limits">
      <Bar label="HOUR" window={limits.hour} testId="reel-limit-hour" />
      <Bar label="DAY" window={limits.day} testId="reel-limit-day" />
    </Flex>
  )
}
```

- [ ] **Step 3: Mount it**

In `web/components/AppShell.tsx`, import it and render immediately after `<UsageMeter usage={status?.usage} />`:

```tsx
          <ReelLimits limits={status?.reel_limits ?? null} />
```

- [ ] **Step 4: Surface the refusal on the control**

`SelectionBar.tsx:70-75` already surfaces `state.errors`, so a refusal will
appear on its own. The problem is the wording: it would read *"1 failed"*, and
nothing failed � the app declined to start. Refusal is not failure, and a
message that conflates them sends you looking for a bug.

Replace the block at `SelectionBar.tsx:69-76` with:

```tsx
      const refused = Object.entries(state.statuses)
        .filter(([, s]) => s === 'quota')
        .map(([sc]) => sc)
      if (refused.length > 0) {
        const why = state.errors?.[refused[0]] ?? 'reel cap spent'
        // Not a failure: the app declined to start. Saying "failed" here
        // sends you looking for a bug that is not there.
        setError(`${refused.length} not fetched � ${why}.`)
        setPhase('error')
        return
      }

      const failed = Object.entries(state.errors ?? {}).filter(
        ([sc]) => state.statuses[sc] !== 'quota',
      )
      if (failed.length > 0) {
        const shown = failed.slice(0, 2).map(([sc, why]) => `${sc}: ${why}`).join(' � ')
        setError(`${failed.length} failed. ${shown}${failed.length > 2 ? ` (+${failed.length - 2} more)` : ''}`)
        setPhase('error')
        return
      }
```

The refusal is checked first, and quota entries are excluded from the failure
list so a refused reel is never counted twice.

- [ ] **Step 5: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Write the e2e test**

Create `web/e2e/limits.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

async function withLimits(page: import('@playwright/test').Page, hour: number, day: number) {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({
      response: res,
      json: {
        ...body,
        reel_limits: {
          hour: { used: hour, max: 20, resets_at: '2026-08-25T12:10:00+00:00' },
          day: { used: day, max: 100, resets_at: '2026-08-25T18:00:00+00:00' },
        },
      },
    })
  })
}

test('both reel windows render as progress', async ({ page }) => {
  await withLimits(page, 7, 31)
  await page.goto('/')

  await expect(page.getByTestId('reel-limit-hour')).toContainText('HOUR 7/20')
  await expect(page.getByTestId('reel-limit-day')).toContainText('DAY 31/100')
})

test('a spent window shows when headroom returns instead of a count', async ({ page }) => {
  await withLimits(page, 20, 40)
  await page.goto('/')

  await expect(page.getByTestId('reel-limit-hour')).not.toContainText('20/20')
  await expect(page.getByTestId('reel-limit-day')).toContainText('DAY 40/100')
})

test('the limits are hidden when the adapter does not scrape', async ({ page }) => {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({ response: res, json: { ...body, reel_limits: null } })
  })

  await page.goto('/')

  await expect(page.getByTestId('reel-limits')).toHaveCount(0)
})
```

- [ ] **Step 7: Vacuity check**

Change `fillFor` to `return '#2ecc71'` unconditionally and re-run the e2e suite — nothing should fail, which tells you the colour is **not** covered by a test. Then restore it, and either accept that (colour is a judgement, not a behaviour) or add an assertion on the fill's computed style. Decide deliberately rather than by accident.

- [ ] **Step 8: Run both suites**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Run: `cd .. && bash scripts/e2e-native.sh`
Expected: both PASS.

- [ ] **Step 9: Commit**

```bash
git add web
git commit -m "feat(web): show the reel caps as progress and refuse at the control"
```

---

## Verification

- [ ] `cd api && ../.venv/Scripts/python.exe -m pytest -q` — green
- [ ] `bash scripts/e2e-native.sh` — green
- [ ] `cd web && npx tsc --noEmit` — clean
- [ ] Against the live Graph stack: a reel that previously failed with "Meta publishes no downloadable file" now downloads an mp4, the hourly bar moves by one, and `/api/status` reports it.
- [ ] Set `IG_REEL_MAX_PER_HOUR=1`, download two reels, and confirm the second is refused at the control with a reset time rather than queued.
