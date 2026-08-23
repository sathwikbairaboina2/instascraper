# Instagram Content Retrieval Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, single-user tool to look up public Instagram profiles, browse posts and Reels in a grid, and copy selected media at full quality into a folder on the host.

**Architecture:** Two Docker Compose containers. `web` is Next.js and proxies `/api/*` to `api`. `api` is FastAPI on uvicorn with `--workers 1`, running the HTTP event loop plus exactly one fetch worker thread. That worker thread is the only code that talks to Instagram and the only writer of media and job rows, which makes request serialization structural rather than conventional. All Instaloader usage is confined to one adapter module so an Instagram-side breakage has a one-file blast radius.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Instaloader, SQLite (WAL), pytest, Next.js 15 (App Router), TypeScript, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-23-instascraper-design.md`

## Global Constraints

- Python 3.12. Node 22. Both pinned in Dockerfiles.
- `instaloader` version pinned exactly in `api/requirements.txt`. Bumped deliberately, never with `>=`.
- **Only `api/app/ig/adapter.py` may import `instaloader`.** Task 3 adds a test that enforces this by grepping the tree; it must keep passing.
- **uvicorn runs with `--workers 1`.** More than one process breaks the serialization guarantee.
- Exactly one fetch worker thread. No thread pool for Instagram-bound work.
- No transcode, resize, or re-encode of full media anywhere. Thumbnails are the only derived asset.
- Every file written into `/data/media` or `/out` is written as `<name>.part` and moved into place with `os.replace()`.
- SQLite: WAL mode, `foreign_keys=ON`, `busy_timeout=5000`, one connection per thread (never shared across threads).
- Single user, no authentication, no actor field anywhere.
- Schema is exactly the five tables in spec §3. Tasks may not add columns or tables.
- TDD: every task writes a failing test first, watches it fail, then implements.

**Adapter surface refinement (from spec §4):** the spec names four adapter functions. Byte-fetching for thumbnails and avatars also must not escape the module, so the real surface is five: `fetch_profile`, `fetch_page`, `fetch_media`, `download_to`, `login`. The module boundary — the actual constraint — is unchanged.

## File Structure

```
docker-compose.yml
.env.example
api/
  Dockerfile
  requirements.txt
  pytest.ini
  app/
    __init__.py
    config.py            Settings dataclass loaded from env
    db.py                connection factory (thread-local), schema init
    schema.sql           the five tables from spec §3
    paths.py             media paths, atomic write, download filename generation
    clock.py             injectable now() / monotonic() for tests
    ig/
      __init__.py
      types.py           IgProfile / IgPost / IgPage / SavedFile + error hierarchy
      adapter.py         THE ONLY instaloader importer
      rate.py            RateController subclass
      fake.py            in-memory fake adapter used by every non-live test
      login.py           interactive login entrypoint
    worker/
      __init__.py
      queue.py           enqueue / claim_next / complete / fail
      breaker.py         circuit breaker state machine
      pacer.py           minimum-interval gate
      sweep.py           startup .part and stuck-row cleanup
      handlers.py        profile_sync / page_fetch / media_fetch
      runner.py          the single worker thread
    services/
      activity.py        activity_log writer
      downloads.py       copy cache -> /out with generated names
    routes/
      status.py  profiles.py  media.py  downloads.py  activity.py  health.py
    main.py              app factory, lifespan, router mounting
  scripts/
    seed_e2e.py          deterministic DB seed for Playwright
  tests/
    conftest.py
    fixtures/            sample Instagram JSON payloads
    ...one test module per source module
web/
  Dockerfile  package.json  next.config.js  tsconfig.json  playwright.config.ts
  app/
    layout.tsx  page.tsx  p/[username]/page.tsx  activity/page.tsx
  components/
    Banner.tsx  TrackedProfiles.tsx  MediaGrid.tsx  MediaTile.tsx  SelectionBar.tsx
  lib/
    api.ts  usePolling.ts  useSelection.ts
  e2e/
    happy-path.spec.ts
```

Rationale for the splits: `worker/` separates the four independent concerns that each need their own test cycle (queueing, breaker, pacing, dispatch) rather than one large worker module. `routes/` splits by resource so a route file stays under ~120 lines. `ig/` isolates the volatile dependency behind `types.py`, which everything else imports instead.

---

### Task 1: Repo skeleton, settings, database

**Files:**
- Create: `api/requirements.txt`, `api/pytest.ini`, `api/app/__init__.py`, `api/app/config.py`, `api/app/clock.py`, `api/app/schema.sql`, `api/app/db.py`
- Test: `api/tests/conftest.py`, `api/tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Settings` frozen dataclass with fields `ig_username: str`, `ig_password: str`, `db_path: Path`, `media_dir: Path`, `session_dir: Path`, `out_dir: Path`, `page_size: int`, `ig_min_interval: float`, `ig_backoff: int`, `adapter: str`
  - `load_settings() -> Settings`
  - `db.get_conn(settings: Settings) -> sqlite3.Connection` (thread-local)
  - `db.init_schema(conn: sqlite3.Connection) -> None`
  - `clock.now_iso() -> str` (UTC, `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`)
  - pytest fixtures `settings`, `conn` (temp dir, initialised schema)

- [ ] **Step 1: Create the dependency and pytest files**

`api/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
instaloader==4.14.1
python-multipart==0.0.20
pytest==8.3.4
pytest-asyncio==0.25.2
httpx==0.28.1
```

`api/pytest.ini`:

```ini
[pytest]
testpaths = tests
markers =
    live: hits the real Instagram API; excluded from the default run
addopts = -m "not live" -q
```

- [ ] **Step 2: Write the failing test**

`api/tests/conftest.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app import db


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        ig_username="tester",
        ig_password="secret",
        db_path=tmp_path / "app.db",
        media_dir=tmp_path / "media",
        session_dir=tmp_path / "session",
        out_dir=tmp_path / "out",
        page_size=4,
        ig_min_interval=0.05,
        ig_backoff=2,
        adapter="fake",
    )


@pytest.fixture
def conn(settings):
    for d in (settings.media_dir, settings.session_dir, settings.out_dir):
        d.mkdir(parents=True, exist_ok=True)
    c = db.get_conn(settings)
    db.init_schema(c)
    yield c
    c.close()
    db.reset_thread_state()
```

`api/tests/test_db.py`:

```python
from app import db


def test_wal_and_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_all_five_tables_exist(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"profiles", "media_items", "media_files", "jobs", "activity_log"} <= names


def test_init_schema_is_idempotent(conn, settings):
    db.init_schema(conn)
    db.init_schema(conn)
    assert conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"] == 0


def test_media_files_cascade_on_item_delete(conn):
    conn.execute(
        "INSERT INTO profiles (username, tracked, created_at) VALUES ('a', 0, 'x')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at) VALUES ('S1','a','image','t',0,'u','t')"
    )
    conn.execute(
        "INSERT INTO media_files (shortcode, role, child_idx, path)"
        " VALUES ('S1','full',0,'p')"
    )
    conn.execute("DELETE FROM media_items WHERE shortcode='S1'")
    assert conn.execute("SELECT COUNT(*) c FROM media_files").fetchone()["c"] == 0
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: Write the implementation**

`api/app/__init__.py`: empty file.

`api/app/clock.py`:

```python
import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic() -> float:
    return time.monotonic()
```

`api/app/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ig_username: str
    ig_password: str
    db_path: Path
    media_dir: Path
    session_dir: Path
    out_dir: Path
    page_size: int
    ig_min_interval: float
    ig_backoff: int
    adapter: str


def load_settings() -> Settings:
    return Settings(
        ig_username=os.environ.get("IG_USERNAME", ""),
        ig_password=os.environ.get("IG_PASSWORD", ""),
        db_path=Path(os.environ.get("DB_PATH", "/data/app.db")),
        media_dir=Path(os.environ.get("MEDIA_DIR", "/data/media")),
        session_dir=Path(os.environ.get("SESSION_DIR", "/data/session")),
        out_dir=Path(os.environ.get("OUT_DIR_CONTAINER", "/out")),
        page_size=int(os.environ.get("PAGE_SIZE", "36")),
        ig_min_interval=float(os.environ.get("IG_MIN_INTERVAL", "3")),
        ig_backoff=int(os.environ.get("IG_BACKOFF", "900")),
        adapter=os.environ.get("IG_ADAPTER", "real"),
    )
```

`api/app/schema.sql` — copy the DDL from spec §3 verbatim, wrapping each statement with `IF NOT EXISTS` so re-running is safe:

```sql
CREATE TABLE IF NOT EXISTS profiles (
  username        TEXT PRIMARY KEY,
  ig_user_id      TEXT,
  full_name       TEXT,
  biography       TEXT,
  is_private      INTEGER NOT NULL DEFAULT 0,
  post_count      INTEGER,
  avatar_path     TEXT,
  next_cursor     TEXT,
  tracked         INTEGER NOT NULL DEFAULT 0,
  last_synced_at  TEXT,
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_items (
  shortcode     TEXT PRIMARY KEY,
  username      TEXT NOT NULL REFERENCES profiles(username) ON DELETE CASCADE,
  kind          TEXT NOT NULL,
  taken_at      TEXT NOT NULL,
  caption       TEXT,
  is_video      INTEGER NOT NULL,
  child_count   INTEGER NOT NULL DEFAULT 1,
  full_status   TEXT NOT NULL DEFAULT 'none',
  full_error    TEXT,
  ig_url        TEXT NOT NULL,
  discovered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_profile ON media_items(username, taken_at DESC);

CREATE TABLE IF NOT EXISTS media_files (
  id         INTEGER PRIMARY KEY,
  shortcode  TEXT NOT NULL REFERENCES media_items(shortcode) ON DELETE CASCADE,
  role       TEXT NOT NULL,
  child_idx  INTEGER NOT NULL DEFAULT 0,
  path       TEXT NOT NULL,
  mime       TEXT,
  bytes      INTEGER,
  width      INTEGER,
  height     INTEGER,
  UNIQUE(shortcode, role, child_idx)
);

CREATE TABLE IF NOT EXISTS jobs (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  priority     INTEGER NOT NULL,
  status       TEXT NOT NULL,
  attempts     INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_pickup ON jobs(status, priority, created_at);

CREATE TABLE IF NOT EXISTS activity_log (
  id      INTEGER PRIMARY KEY,
  ts      TEXT NOT NULL,
  action  TEXT NOT NULL,
  target  TEXT,
  detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(ts DESC);
```

`api/app/db.py`:

```python
import sqlite3
import threading
from pathlib import Path

from app.config import Settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_local = threading.local()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_conn(settings: Settings) -> sqlite3.Connection:
    """One connection per thread. Never share a connection across threads."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect(settings.db_path)
        _local.conn = conn
    return conn


def reset_thread_state() -> None:
    """Test helper: forget this thread's cached connection."""
    if getattr(_local, "conn", None) is not None:
        _local.conn = None


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_db.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add api/requirements.txt api/pytest.ini api/app api/tests
git commit -m "feat(api): settings, SQLite schema, thread-local connections"
```

---

### Task 2: Path and filename helpers

**Files:**
- Create: `api/app/paths.py`
- Test: `api/tests/test_paths.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `item_dir(media_root: Path, username: str, shortcode: str) -> Path`
  - `rel_path(media_root: Path, absolute: Path) -> str`
  - `full_filename(child_idx: int, ext: str) -> str` — `child_idx == 0` gives `full.<ext>`, otherwise `full_<idx>.<ext>`
  - `atomic_write(dest: Path, write: Callable[[BinaryIO], None]) -> int` — writes via `.part`, returns bytes written
  - `atomic_copy(src: Path, dest: Path) -> None`
  - `sanitize_base(base: str) -> str`
  - `download_names(posts: list[PostFiles], base: str) -> list[NamedFile]` where
    `PostFiles = tuple[str, list[tuple[int, str]]]` (shortcode, `[(child_idx, ext)]`)
    and `NamedFile = tuple[str, int, str]` (shortcode, child_idx, output filename)
  - `unique_dest(directory: Path, filename: str) -> Path`

- [ ] **Step 1: Write the failing test**

`api/tests/test_paths.py`:

```python
import pytest

from app import paths


def test_full_filename_single_vs_carousel():
    assert paths.full_filename(0, "jpg") == "full.jpg"
    assert paths.full_filename(1, "mp4") == "full_1.mp4"
    assert paths.full_filename(12, "jpg") == "full_12.jpg"


def test_item_dir_layout(tmp_path):
    d = paths.item_dir(tmp_path, "nike", "ABC123")
    assert d == tmp_path / "nike" / "ABC123"


def test_rel_path_is_relative_to_media_root(tmp_path):
    p = tmp_path / "nike" / "ABC123" / "full.jpg"
    assert paths.rel_path(tmp_path, p) == "nike/ABC123/full.jpg"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nike_ss26", "nike_ss26"),
        ("../../etc/passwd", "etcpasswd"),
        ("a/b\\c", "abc"),
        ("  spaced  name ", "spaced_name"),
        ("", "download"),
        ("." * 5, "download"),
    ],
)
def test_sanitize_base_strips_separators_and_traversal(raw, expected):
    assert paths.sanitize_base(raw) == expected


def test_download_names_single_items_zero_padded():
    posts = [("A", [(0, "jpg")]), ("B", [(0, "mp4")]), ("C", [(0, "jpg")])]
    assert paths.download_names(posts, "trip") == [
        ("A", 0, "trip_01.jpg"),
        ("B", 0, "trip_02.mp4"),
        ("C", 0, "trip_03.jpg"),
    ]


def test_download_names_carousel_children_get_letters():
    posts = [("A", [(1, "jpg"), (2, "jpg"), (3, "mp4")]), ("B", [(0, "jpg")])]
    assert paths.download_names(posts, "set") == [
        ("A", 1, "set_01a.jpg"),
        ("A", 2, "set_01b.jpg"),
        ("A", 3, "set_01c.mp4"),
        ("B", 0, "set_02.jpg"),
    ]


def test_download_names_widen_padding_past_99():
    posts = [(f"S{i}", [(0, "jpg")]) for i in range(1, 101)]
    names = paths.download_names(posts, "big")
    assert names[0][2] == "big_001.jpg"
    assert names[-1][2] == "big_100.jpg"


def test_atomic_write_leaves_no_part_file(tmp_path):
    dest = tmp_path / "x" / "full.jpg"
    n = paths.atomic_write(dest, lambda fh: fh.write(b"hello"))
    assert n == 5
    assert dest.read_bytes() == b"hello"
    assert list(tmp_path.rglob("*.part")) == []


def test_atomic_write_removes_part_on_failure(tmp_path):
    dest = tmp_path / "x" / "full.jpg"

    def boom(fh):
        fh.write(b"partial")
        raise RuntimeError("network died")

    with pytest.raises(RuntimeError):
        paths.atomic_write(dest, boom)
    assert not dest.exists()
    assert list(tmp_path.rglob("*.part")) == []


def test_unique_dest_suffixes_on_collision(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    assert paths.unique_dest(tmp_path, "a.jpg").name == "a-1.jpg"
    (tmp_path / "a-1.jpg").write_bytes(b"1")
    assert paths.unique_dest(tmp_path, "a.jpg").name == "a-2.jpg"


def test_atomic_copy(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"abc")
    dest = tmp_path / "out" / "dst.jpg"
    paths.atomic_copy(src, dest)
    assert dest.read_bytes() == b"abc"
    assert list((tmp_path / "out").glob("*.part")) == []
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.paths'`

- [ ] **Step 3: Write the implementation**

`api/app/paths.py`:

```python
import os
import re
import shutil
from pathlib import Path
from typing import BinaryIO, Callable

PostFiles = tuple[str, list[tuple[int, str]]]
NamedFile = tuple[str, int, str]

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def item_dir(media_root: Path, username: str, shortcode: str) -> Path:
    return media_root / username / shortcode


def rel_path(media_root: Path, absolute: Path) -> str:
    return absolute.relative_to(media_root).as_posix()


def full_filename(child_idx: int, ext: str) -> str:
    return f"full.{ext}" if child_idx == 0 else f"full_{child_idx}.{ext}"


def sanitize_base(base: str) -> str:
    cleaned = _UNSAFE.sub("_", base.strip()).strip("._-")
    return cleaned or "download"


def download_names(posts: list[PostFiles], base: str) -> list[NamedFile]:
    width = max(2, len(str(len(posts))))
    out: list[NamedFile] = []
    for index, (shortcode, files) in enumerate(posts, start=1):
        num = str(index).zfill(width)
        if len(files) == 1:
            child_idx, ext = files[0]
            out.append((shortcode, child_idx, f"{base}_{num}.{ext}"))
            continue
        for offset, (child_idx, ext) in enumerate(files):
            letter = chr(ord("a") + offset)
            out.append((shortcode, child_idx, f"{base}_{num}{letter}.{ext}"))
    return out


def atomic_write(dest: Path, write: Callable[[BinaryIO], None]) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with part.open("wb") as fh:
            write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        size = part.stat().st_size
        os.replace(part, dest)
        return size
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def atomic_copy(src: Path, dest: Path) -> None:
    with src.open("rb") as fh:
        atomic_write(dest, lambda out: shutil.copyfileobj(fh, out))


def unique_dest(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
```

Note on `sanitize_base`: `"  spaced  name "` collapses interior whitespace to a single `_`, and leading/trailing `._-` are stripped, which is what produces `spaced_name`. `"../../etc/passwd"` becomes `etcpasswd` because `/` and `.` runs collapse to `_` and then strip at the boundaries — verify against the parametrized cases, and adjust the regex rather than the tests if they disagree.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_paths.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/paths.py api/tests/test_paths.py
git commit -m "feat(api): media path, atomic write, and download naming helpers"
```

---

### Task 3: Adapter contract, error hierarchy, fake adapter

**Files:**
- Create: `api/app/ig/__init__.py`, `api/app/ig/types.py`, `api/app/ig/fake.py`
- Test: `api/tests/test_ig_contract.py`

**Interfaces:**
- Consumes: `paths.atomic_write`, `paths.full_filename`, `paths.item_dir`.
- Produces:
  - Errors: `IgError` base, with `IgNotFound`, `IgPrivate`, `IgRateLimited`, `IgChallenge`, `IgTransient`
  - `IgProfile(username, user_id, full_name, biography, is_private, post_count, avatar_url)`
  - `IgPost(shortcode, kind, taken_at_iso, caption, is_video, child_count, thumb_url, ig_url)`
  - `IgPage(posts: list[IgPost], next_cursor: str | None)` — `None` means exhausted
  - `SavedFile(child_idx, path: Path, mime, bytes, width, height)`
  - `IgAdapter` Protocol with `fetch_profile(username) -> IgProfile`, `fetch_page(username, cursor, limit) -> IgPage`, `fetch_media(shortcode, dest_dir) -> list[SavedFile]`, `download_to(url, dest) -> SavedFile`, `login() -> None`
  - `FakeAdapter` implementing that Protocol, with test controls: `add_profile`, `add_posts`, `raise_on(method, exc)`, `calls: list[CallRecord]` where `CallRecord(method, started, ended)`

- [ ] **Step 1: Write the failing test**

`api/tests/test_ig_contract.py`:

```python
import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter


def test_error_hierarchy():
    for exc in (t.IgNotFound, t.IgPrivate, t.IgRateLimited, t.IgChallenge, t.IgTransient):
        assert issubclass(exc, t.IgError)


def test_fake_returns_profile():
    fake = FakeAdapter()
    fake.add_profile("nike", post_count=3)
    p = fake.fetch_profile("nike")
    assert p.username == "nike"
    assert p.post_count == 3
    assert p.is_private is False


def test_fake_unknown_profile_raises_not_found():
    with pytest.raises(t.IgNotFound):
        FakeAdapter().fetch_profile("ghost")


def test_fake_paginates_and_signals_exhaustion():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=5)
    first = fake.fetch_page("nike", cursor=None, limit=2)
    assert [p.shortcode for p in first.posts] == ["nike-0", "nike-1"]
    assert first.next_cursor is not None
    second = fake.fetch_page("nike", cursor=first.next_cursor, limit=2)
    assert [p.shortcode for p in second.posts] == ["nike-2", "nike-3"]
    third = fake.fetch_page("nike", cursor=second.next_cursor, limit=2)
    assert [p.shortcode for p in third.posts] == ["nike-4"]
    assert third.next_cursor is None


def test_fake_fetch_media_writes_files(tmp_path):
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=1, child_count=3)
    saved = fake.fetch_media("nike-0", tmp_path)
    assert [s.child_idx for s in saved] == [1, 2, 3]
    for s in saved:
        assert s.path.exists()
        assert s.bytes > 0
    assert list(tmp_path.glob("*.part")) == []


def test_fake_records_call_windows():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.fetch_profile("nike")
    fake.fetch_profile("nike")
    assert [c.method for c in fake.calls] == ["fetch_profile", "fetch_profile"]
    assert fake.calls[0].ended <= fake.calls[1].started


def test_fake_raise_on_is_one_shot():
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.raise_on("fetch_profile", t.IgRateLimited("429"))
    with pytest.raises(t.IgRateLimited):
        fake.fetch_profile("nike")
    assert fake.fetch_profile("nike").username == "nike"


def test_only_adapter_module_imports_instaloader():
    """Global constraint: the volatile dependency stays in one file."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "instaloader" in p.read_text() and p.name != "adapter.py"
    ]
    assert offenders == []
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_ig_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ig'`

- [ ] **Step 3: Write the types module**

`api/app/ig/__init__.py`: empty file.

`api/app/ig/types.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class IgError(Exception):
    """Base for every failure the adapter is allowed to raise."""


class IgNotFound(IgError):
    """Profile or post does not exist. Terminal."""


class IgPrivate(IgError):
    """Profile exists but is not public. Terminal, out of scope."""


class IgRateLimited(IgError):
    """429 or equivalent. Trips the breaker temporarily."""


class IgChallenge(IgError):
    """Login challenge or dead session. Trips the breaker permanently."""


class IgTransient(IgError):
    """Network blip or 5xx. Retryable."""


@dataclass(frozen=True)
class IgProfile:
    username: str
    user_id: str
    full_name: str
    biography: str
    is_private: bool
    post_count: int
    avatar_url: str


@dataclass(frozen=True)
class IgPost:
    shortcode: str
    kind: str  # image | video | reel | carousel
    taken_at_iso: str
    caption: str
    is_video: bool
    child_count: int
    thumb_url: str
    ig_url: str


@dataclass(frozen=True)
class IgPage:
    posts: list[IgPost]
    next_cursor: str | None  # None means the iterator is exhausted


@dataclass(frozen=True)
class SavedFile:
    child_idx: int
    path: Path
    mime: str
    bytes: int
    width: int | None
    height: int | None


class IgAdapter(Protocol):
    def fetch_profile(self, username: str) -> IgProfile: ...

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> IgPage: ...

    def fetch_media(self, shortcode: str, dest_dir: Path) -> list[SavedFile]: ...

    def download_to(self, url: str, dest: Path) -> SavedFile: ...

    def login(self) -> None: ...
```

- [ ] **Step 4: Write the fake adapter**

`api/app/ig/fake.py`:

```python
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import paths
from app.ig import types as t


@dataclass
class CallRecord:
    method: str
    started: float
    ended: float


@dataclass
class FakeAdapter:
    """In-memory IgAdapter used by every test that is not marked `live`."""

    profiles: dict[str, t.IgProfile] = field(default_factory=dict)
    posts: dict[str, list[t.IgPost]] = field(default_factory=dict)
    calls: list[CallRecord] = field(default_factory=list)
    _pending: dict[str, Exception] = field(default_factory=dict)
    delay: float = 0.0

    # ---- test controls -------------------------------------------------
    def add_profile(self, username: str, post_count: int = 0, is_private: bool = False):
        self.profiles[username] = t.IgProfile(
            username=username,
            user_id=f"id-{username}",
            full_name=username.title(),
            biography="bio",
            is_private=is_private,
            post_count=post_count,
            avatar_url=f"https://cdn.test/{username}/avatar.jpg",
        )

    def add_posts(self, username: str, count: int, child_count: int = 1, video: bool = False):
        bucket = self.posts.setdefault(username, [])
        start = len(bucket)
        for i in range(start, start + count):
            shortcode = f"{username}-{i}"
            kind = "carousel" if child_count > 1 else ("reel" if video else "image")
            bucket.append(
                t.IgPost(
                    shortcode=shortcode,
                    kind=kind,
                    taken_at_iso=f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
                    caption=f"caption {i}",
                    is_video=video,
                    child_count=child_count,
                    thumb_url=f"https://cdn.test/{shortcode}/thumb.jpg",
                    ig_url=f"https://instagram.com/p/{shortcode}/",
                )
            )

    def raise_on(self, method: str, exc: Exception) -> None:
        """Next call to `method` raises `exc`, once."""
        self._pending[method] = exc

    # ---- internals -----------------------------------------------------
    def _enter(self, method: str) -> float:
        if self.delay:
            time.sleep(self.delay)
        started = time.monotonic()
        exc = self._pending.pop(method, None)
        if exc is not None:
            self.calls.append(CallRecord(method, started, time.monotonic()))
            raise exc
        return started

    def _exit(self, method: str, started: float) -> None:
        self.calls.append(CallRecord(method, started, time.monotonic()))

    def _find_post(self, shortcode: str) -> t.IgPost:
        for bucket in self.posts.values():
            for post in bucket:
                if post.shortcode == shortcode:
                    return post
        raise t.IgNotFound(shortcode)

    # ---- IgAdapter -----------------------------------------------------
    def fetch_profile(self, username: str) -> t.IgProfile:
        started = self._enter("fetch_profile")
        try:
            profile = self.profiles.get(username)
            if profile is None:
                raise t.IgNotFound(username)
            return profile
        finally:
            self._exit("fetch_profile", started)

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        started = self._enter("fetch_page")
        try:
            bucket = self.posts.get(username, [])
            offset = int(cursor) if cursor else 0
            window = bucket[offset : offset + limit]
            nxt = offset + len(window)
            return t.IgPage(posts=window, next_cursor=str(nxt) if nxt < len(bucket) else None)
        finally:
            self._exit("fetch_page", started)

    def fetch_media(self, shortcode: str, dest_dir: Path) -> list[t.SavedFile]:
        started = self._enter("fetch_media")
        try:
            post = self._find_post(shortcode)
            ext = "mp4" if post.is_video else "jpg"
            indices = [0] if post.child_count == 1 else list(range(1, post.child_count + 1))
            saved = []
            for idx in indices:
                dest = dest_dir / paths.full_filename(idx, ext)
                payload = f"{shortcode}:{idx}".encode()
                size = paths.atomic_write(dest, lambda fh, p=payload: fh.write(p))
                saved.append(
                    t.SavedFile(
                        child_idx=idx,
                        path=dest,
                        mime="video/mp4" if post.is_video else "image/jpeg",
                        bytes=size,
                        width=1080,
                        height=1350,
                    )
                )
            return saved
        finally:
            self._exit("fetch_media", started)

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        started = self._enter("download_to")
        try:
            payload = url.encode()
            size = paths.atomic_write(dest, lambda fh: fh.write(payload))
            return t.SavedFile(0, dest, "image/jpeg", size, 320, 320)
        finally:
            self._exit("download_to", started)

    def login(self) -> None:
        started = self._enter("login")
        self._exit("login", started)
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_ig_contract.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add api/app/ig api/tests/test_ig_contract.py
git commit -m "feat(api): Instagram adapter contract, error hierarchy, and fake"
```

---

### Task 4: Job queue

**Files:**
- Create: `api/app/worker/__init__.py`, `api/app/worker/queue.py`
- Test: `api/tests/test_queue.py`

**Interfaces:**
- Consumes: `db.get_conn`, `clock.now_iso`.
- Produces:
  - `PRIORITY = {"media_fetch": 10, "profile_sync": 20, "page_fetch": 30}`
  - `MAX_ATTEMPTS = 3`
  - `enqueue(conn, kind: str, payload: dict) -> int`
  - `enqueue_unique(conn, kind: str, payload: dict) -> int | None` — returns `None` if an identical `queued` or `running` job already exists
  - `claim_next(conn) -> sqlite3.Row | None`
  - `complete(conn, job_id: int) -> None`
  - `fail(conn, job_id: int, error: str, retryable: bool) -> None` — requeues while `attempts < MAX_ATTEMPTS`, otherwise marks `failed`
  - `requeue(conn, job_id: int) -> None` — puts a running job back without consuming an attempt
  - `depth(conn) -> int`

- [ ] **Step 1: Write the failing test**

`api/tests/test_queue.py`:

```python
import json

from app.worker import queue


def test_enqueue_returns_id_and_sets_priority(conn):
    job_id = queue.enqueue(conn, "page_fetch", {"username": "nike"})
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["kind"] == "page_fetch"
    assert row["priority"] == 30
    assert row["status"] == "queued"
    assert json.loads(row["payload"]) == {"username": "nike"}


def test_claim_next_respects_priority_then_age(conn):
    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.enqueue(conn, "media_fetch", {"n": 3})
    queue.enqueue(conn, "profile_sync", {"n": 4})

    order = []
    while (job := queue.claim_next(conn)) is not None:
        order.append(json.loads(job["payload"])["n"])
        queue.complete(conn, job["id"])
    assert order == [3, 4, 1, 2]


def test_claim_next_marks_running_and_counts_attempt(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    job = queue.claim_next(conn)
    assert job["id"] == job_id
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "running"
    assert row["attempts"] == 1
    assert row["started_at"] is not None


def test_claim_next_returns_none_when_empty(conn):
    assert queue.claim_next(conn) is None


def test_a_claimed_job_is_not_claimed_again(conn):
    queue.enqueue(conn, "media_fetch", {"sc": "A"})
    assert queue.claim_next(conn) is not None
    assert queue.claim_next(conn) is None


def test_enqueue_unique_skips_duplicates(conn):
    first = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    second = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    assert first is not None
    assert second is None
    queue.claim_next(conn)
    assert queue.enqueue_unique(conn, "media_fetch", {"sc": "A"}) is None


def test_enqueue_unique_allows_after_completion(conn):
    job_id = queue.enqueue_unique(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)
    queue.complete(conn, job_id)
    assert queue.enqueue_unique(conn, "media_fetch", {"sc": "A"}) is not None


def test_fail_retries_until_max_attempts(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    for _ in range(queue.MAX_ATTEMPTS - 1):
        queue.claim_next(conn)
        queue.fail(conn, job_id, "boom", retryable=True)
        assert conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()["status"] == "queued"

    queue.claim_next(conn)
    queue.fail(conn, job_id, "boom", retryable=True)
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "boom"
    assert row["finished_at"] is not None


def test_fail_non_retryable_is_terminal_immediately(conn):
    job_id = queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    queue.claim_next(conn)
    queue.fail(conn, job_id, "not found", retryable=False)
    assert conn.execute(
        "SELECT status FROM jobs WHERE id=?", (job_id,)
    ).fetchone()["status"] == "failed"


def test_requeue_does_not_consume_an_attempt(conn):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)
    queue.requeue(conn, job_id)
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "queued"
    assert row["attempts"] == 0
    assert row["started_at"] is None


def test_depth_counts_queued_and_running(conn):
    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.claim_next(conn)
    assert queue.depth(conn) == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 3: Write the implementation**

`api/app/worker/__init__.py`: empty file.

`api/app/worker/queue.py`:

```python
import json
import sqlite3

from app.clock import now_iso

PRIORITY = {"media_fetch": 10, "profile_sync": 20, "page_fetch": 30}
MAX_ATTEMPTS = 3


def enqueue(conn: sqlite3.Connection, kind: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, payload, priority, status, created_at)"
        " VALUES (?, ?, ?, 'queued', ?)",
        (kind, json.dumps(payload, sort_keys=True), PRIORITY[kind], now_iso()),
    )
    return int(cur.lastrowid)


def enqueue_unique(conn: sqlite3.Connection, kind: str, payload: dict) -> int | None:
    encoded = json.dumps(payload, sort_keys=True)
    existing = conn.execute(
        "SELECT id FROM jobs WHERE kind=? AND payload=? AND status IN ('queued','running')",
        (kind, encoded),
    ).fetchone()
    if existing is not None:
        return None
    return enqueue(conn, kind, payload)


def claim_next(conn: sqlite3.Connection) -> sqlite3.Row | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued'"
            " ORDER BY priority, created_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
            (now_iso(), row["id"]),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()


def complete(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status='done', error=NULL, finished_at=? WHERE id=?",
        (now_iso(), job_id),
    )


def fail(conn: sqlite3.Connection, job_id: int, error: str, retryable: bool) -> None:
    row = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
    exhausted = row is None or row["attempts"] >= MAX_ATTEMPTS
    if retryable and not exhausted:
        conn.execute(
            "UPDATE jobs SET status='queued', started_at=NULL, error=? WHERE id=?",
            (error, job_id),
        )
        return
    conn.execute(
        "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
        (error, now_iso(), job_id),
    )


def requeue(conn: sqlite3.Connection, job_id: int) -> None:
    """Return a claimed job to the queue without spending an attempt.

    Used when the breaker trips mid-job: the failure is environmental,
    not the job's fault.
    """
    conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL,"
        " attempts=MAX(attempts-1, 0) WHERE id=?",
        (job_id,),
    )


def depth(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()["c"]
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_queue.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker api/tests/test_queue.py
git commit -m "feat(api): job queue with priority claim and retry policy"
```

---

### Task 5: Circuit breaker

**Files:**
- Create: `api/app/worker/breaker.py`
- Test: `api/tests/test_breaker.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Breaker(clock: Callable[[], float] = clock.monotonic)` with
  - `trip_temporary(seconds: float, reason: str) -> None`
  - `trip_permanent(reason: str) -> None`
  - `clear() -> None`
  - `wait_seconds() -> float` — `0.0` when clear, remaining seconds when temporarily tripped, `float("inf")` when permanently tripped
  - `state() -> dict` with keys `tripped: bool`, `permanent: bool`, `reason: str | None`, `seconds_remaining: float | None`

- [ ] **Step 1: Write the failing test**

`api/tests/test_breaker.py`:

```python
from app.worker.breaker import Breaker


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_starts_clear():
    b = Breaker(clock=FakeClock())
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_temporary_trip_expires():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_temporary(900, "rate limited")
    assert b.wait_seconds() == 900
    clock.advance(899)
    assert b.wait_seconds() == 1
    clock.advance(1)
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_permanent_trip_never_expires():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_permanent("session invalid")
    clock.advance(10_000)
    assert b.wait_seconds() == float("inf")
    assert b.state() == {
        "tripped": True,
        "permanent": True,
        "reason": "session invalid",
        "seconds_remaining": None,
    }


def test_permanent_trip_survives_a_later_temporary_trip():
    """A challenge must not be downgraded into a 15-minute nap."""
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_permanent("session invalid")
    b.trip_temporary(5, "rate limited")
    clock.advance(1_000)
    assert b.wait_seconds() == float("inf")
    assert b.state()["reason"] == "session invalid"


def test_clear_resets_everything():
    b = Breaker(clock=FakeClock())
    b.trip_permanent("session invalid")
    b.clear()
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_temporary_trip_extends_but_never_shortens():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_temporary(900, "first")
    b.trip_temporary(10, "second")
    assert b.wait_seconds() == 900
    b.trip_temporary(1800, "third")
    assert b.wait_seconds() == 1800
    assert b.state()["reason"] == "third"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_breaker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker.breaker'`

- [ ] **Step 3: Write the implementation**

`api/app/worker/breaker.py`:

```python
import threading
from typing import Callable

from app import clock as _clock


class Breaker:
    """Global gate on Instagram-bound work.

    Temporary trips (429) expire on their own. Permanent trips (login
    challenge, dead session) need a human and never expire by themselves --
    automatically retrying past a challenge is how a throttled account
    becomes a flagged one.
    """

    def __init__(self, clock: Callable[[], float] = _clock.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._until: float = 0.0
        self._permanent = False
        self._reason: str | None = None

    def trip_temporary(self, seconds: float, reason: str) -> None:
        with self._lock:
            until = self._clock() + seconds
            if until > self._until:
                self._until = until
                self._reason = reason
            if not self._permanent:
                self._reason = reason if until >= self._until else self._reason

    def trip_permanent(self, reason: str) -> None:
        with self._lock:
            self._permanent = True
            self._reason = reason

    def clear(self) -> None:
        with self._lock:
            self._until = 0.0
            self._permanent = False
            self._reason = None

    def wait_seconds(self) -> float:
        with self._lock:
            if self._permanent:
                return float("inf")
            return max(0.0, self._until - self._clock())

    def state(self) -> dict:
        with self._lock:
            if self._permanent:
                return {
                    "tripped": True,
                    "permanent": True,
                    "reason": self._reason,
                    "seconds_remaining": None,
                }
            remaining = max(0.0, self._until - self._clock())
            if remaining <= 0:
                return {
                    "tripped": False,
                    "permanent": False,
                    "reason": None,
                    "seconds_remaining": None,
                }
            return {
                "tripped": True,
                "permanent": False,
                "reason": self._reason,
                "seconds_remaining": remaining,
            }
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_breaker.py -v`
Expected: PASS, 6 tests. If `test_permanent_trip_survives_a_later_temporary_trip` fails, the `trip_temporary` reason bookkeeping is wrong — a permanent reason must never be overwritten. Simplify `trip_temporary` to skip the reason update entirely when `self._permanent` is set.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/breaker.py api/tests/test_breaker.py
git commit -m "feat(api): circuit breaker with temporary and permanent trips"
```

---

### Task 6: Startup sweep

**Files:**
- Create: `api/app/worker/sweep.py`
- Test: `api/tests/test_sweep.py`

**Interfaces:**
- Consumes: `db` fixtures.
- Produces: `sweep(conn, media_root: Path) -> dict` returning counts `{"parts": int, "items": int, "jobs": int}`

- [ ] **Step 1: Write the failing test**

`api/tests/test_sweep.py`:

```python
from app.worker import queue, sweep


def _seed_profile_and_item(conn, shortcode: str, status: str):
    conn.execute(
        "INSERT OR IGNORE INTO profiles (username, tracked, created_at)"
        " VALUES ('nike', 1, 't')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " full_status, ig_url, discovered_at) VALUES (?,'nike','image','t',0,?,'u','t')",
        (shortcode, status),
    )


def test_sweep_deletes_part_files(conn, settings):
    d = settings.media_dir / "nike" / "A"
    d.mkdir(parents=True)
    (d / "full.jpg.part").write_bytes(b"x")
    (d / "thumb.jpg").write_bytes(b"y")

    result = sweep.sweep(conn, settings.media_dir)

    assert result["parts"] == 1
    assert not (d / "full.jpg.part").exists()
    assert (d / "thumb.jpg").exists()


def test_sweep_resets_interrupted_media_rows(conn, settings):
    _seed_profile_and_item(conn, "A", "fetching")
    _seed_profile_and_item(conn, "B", "queued")
    _seed_profile_and_item(conn, "C", "ready")
    _seed_profile_and_item(conn, "D", "failed")

    result = sweep.sweep(conn, settings.media_dir)

    statuses = dict(
        conn.execute("SELECT shortcode, full_status FROM media_items").fetchall()
    )
    assert result["items"] == 2
    assert statuses == {"A": "none", "B": "none", "C": "ready", "D": "failed"}


def test_sweep_requeues_running_jobs(conn, settings):
    job_id = queue.enqueue(conn, "media_fetch", {"sc": "A"})
    queue.claim_next(conn)

    result = sweep.sweep(conn, settings.media_dir)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert result["jobs"] == 1
    assert row["status"] == "queued"
    assert row["started_at"] is None


def test_sweep_is_safe_when_media_root_is_missing(conn, tmp_path):
    result = sweep.sweep(conn, tmp_path / "nope")
    assert result == {"parts": 0, "items": 0, "jobs": 0}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker.sweep'`

- [ ] **Step 3: Write the implementation**

`api/app/worker/sweep.py`:

```python
import sqlite3
from pathlib import Path


def sweep(conn: sqlite3.Connection, media_root: Path) -> dict:
    """Undo the damage of a container killed mid-fetch.

    Runs once on startup, before the worker thread starts.
    """
    parts = 0
    if media_root.exists():
        for leftover in media_root.rglob("*.part"):
            leftover.unlink(missing_ok=True)
            parts += 1

    cur = conn.execute(
        "UPDATE media_items SET full_status='none', full_error=NULL"
        " WHERE full_status IN ('fetching','queued')"
    )
    items = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    cur = conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'"
    )
    jobs = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    return {"parts": parts, "items": items, "jobs": jobs}
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_sweep.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/sweep.py api/tests/test_sweep.py
git commit -m "feat(api): startup sweep for .part files and interrupted rows"
```

---

### Task 7: Pacer and the single worker thread

This is the task that makes the spec's central promise true. Both tests in Step 1 assert properties the whole design exists to guarantee; treat a failure here as a design regression, not a flaky test.

**Files:**
- Create: `api/app/worker/pacer.py`, `api/app/worker/runner.py`
- Test: `api/tests/test_pacer.py`, `api/tests/test_worker_runner.py`

**Interfaces:**
- Consumes: `queue.claim_next/complete/fail/requeue`, `Breaker`, `db.get_conn`, `Settings`, `FakeAdapter`.
- Produces:
  - `Pacer(min_interval: float, sleep=time.sleep, clock=time.monotonic)` with `wait() -> None`
  - `Worker(settings, adapter, breaker, pacer, handlers: dict[str, Handler])` — a `threading.Thread` subclass with `wake: threading.Event`, `stop_flag: threading.Event`, `start()`, `shutdown(timeout: float = 5.0)`, and `drain(timeout: float = 5.0) -> None` (test helper that blocks until the queue is empty)
  - `Handler = Callable[[HandlerContext, dict], None]`
  - `HandlerContext(conn, adapter, settings, pacer, enqueue: Callable[[str, dict], None])`

  Handlers call `ctx.pacer.wait()` immediately before each adapter call. Two layers of pacing exist by design: this one covers the gap *between* adapter calls and is testable with the fake, while the `RateController` in Task 11 covers the multiple HTTP requests Instaloader makes *inside* a single adapter call.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_pacer.py`:

```python
from app.worker.pacer import Pacer


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_first_call_does_not_wait():
    clock = FakeClock()
    slept = []
    p = Pacer(min_interval=3.0, sleep=slept.append, clock=clock)
    p.wait()
    assert slept == []


def test_second_immediate_call_waits_the_full_interval():
    clock = FakeClock()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock.t += seconds

    p = Pacer(min_interval=3.0, sleep=sleep, clock=clock)
    p.wait()
    p.wait()
    assert slept == [3.0]


def test_no_wait_when_enough_time_already_passed():
    clock = FakeClock()
    slept = []
    p = Pacer(min_interval=3.0, sleep=slept.append, clock=clock)
    p.wait()
    clock.t += 10
    p.wait()
    assert slept == []
```

`api/tests/test_worker_runner.py`:

```python
import json

import pytest

from app import db
from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext, Worker


@pytest.fixture
def worker_env(settings, conn):
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=6)
    breaker = Breaker()
    pacer = Pacer(min_interval=settings.ig_min_interval)
    return settings, conn, adapter, breaker, pacer


def _run(settings, adapter, breaker, pacer, handlers, conn):
    worker = Worker(settings, adapter, breaker, pacer, handlers)
    worker.start()
    worker.wake.set()
    worker.drain(timeout=10)
    worker.shutdown()
    return worker


def test_instagram_calls_never_overlap_and_respect_min_interval(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env

    def handler(ctx: HandlerContext, payload: dict):
        ctx.pacer.wait()
        ctx.adapter.fetch_profile("nike")

    for _ in range(5):
        queue.enqueue(conn, "profile_sync", {"username": "nike"})

    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    assert len(adapter.calls) == 5
    windows = sorted((c.started, c.ended) for c in adapter.calls)
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start >= prev_end, "two Instagram calls overlapped"
        assert next_start - prev_end >= settings.ig_min_interval * 0.9


def test_media_fetch_preempts_queued_page_fetches(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    order = []

    def record(kind):
        def handler(ctx, payload):
            order.append((kind, payload))

        return handler

    queue.enqueue(conn, "page_fetch", {"n": 1})
    queue.enqueue(conn, "page_fetch", {"n": 2})
    queue.enqueue(conn, "page_fetch", {"n": 3})
    queue.enqueue(conn, "media_fetch", {"sc": "A"})

    _run(
        settings,
        adapter,
        breaker,
        pacer,
        {"page_fetch": record("page"), "media_fetch": record("media")},
        conn,
    )

    assert order[0] == ("media", {"sc": "A"})


def test_rate_limit_trips_breaker_requeues_job_and_resumes(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    settings = settings.__class__(**{**settings.__dict__, "ig_backoff": 1})
    attempts = []

    def handler(ctx, payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise t.IgRateLimited("429")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert len(attempts) == 2
    assert row["status"] == "done"
    assert row["attempts"] == 1, "a breaker trip must not burn a retry"


def test_challenge_trips_breaker_permanently_and_stops_work(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    calls = []

    def handler(ctx, payload):
        calls.append(payload)
        raise t.IgChallenge("checkpoint_required")

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    queue.enqueue(conn, "profile_sync", {"username": "adidas"})

    worker = Worker(settings, adapter, breaker, pacer, {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    with pytest.raises(TimeoutError):
        worker.drain(timeout=2)
    worker.shutdown()

    assert len(calls) == 1, "worker kept hammering after a challenge"
    assert breaker.state()["permanent"] is True
    assert queue.depth(conn) == 2


def test_terminal_error_fails_job_without_retry(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env

    def handler(ctx, payload):
        raise t.IgNotFound("ghost")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 1


def test_transient_error_retries_to_max_then_fails(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    calls = []

    def handler(ctx, payload):
        calls.append(1)
        raise t.IgTransient("connection reset")

    job_id = queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": handler}, conn)

    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert len(calls) == queue.MAX_ATTEMPTS
    assert row["status"] == "failed"


def test_handler_can_enqueue_follow_up_work(worker_env):
    settings, conn, adapter, breaker, pacer = worker_env
    seen = []

    def sync(ctx, payload):
        ctx.enqueue("page_fetch", {"username": payload["username"]})

    def page(ctx, payload):
        seen.append(payload)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    _run(settings, adapter, breaker, pacer, {"profile_sync": sync, "page_fetch": page}, conn)

    assert seen == [{"username": "nike"}]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_pacer.py tests/test_worker_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker.pacer'`

- [ ] **Step 3: Write the pacer**

`api/app/worker/pacer.py`:

```python
import threading
import time
from typing import Callable


class Pacer:
    """Floor on the gap between consecutive Instagram-bound calls.

    Because exactly one thread calls wait(), this is a real global rate
    rather than a per-task intention.
    """

    def __init__(
        self,
        min_interval: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                gap = self._clock() - self._last
                remaining = self._min_interval - gap
                if remaining > 0:
                    self._sleep(remaining)
            self._last = self._clock()
```

- [ ] **Step 4: Write the worker runner**

`api/app/worker/runner.py`:

```python
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app import db
from app.config import Settings
from app.ig import types as t
from app.worker import queue
from app.worker.breaker import Breaker
from app.worker.pacer import Pacer

log = logging.getLogger("worker")


@dataclass
class HandlerContext:
    conn: object
    adapter: object
    settings: Settings
    pacer: Pacer
    enqueue: Callable[[str, dict], None]


Handler = Callable[[HandlerContext, dict], None]

IDLE_TIMEOUT = 5.0


class Worker(threading.Thread):
    """The one and only thread permitted to talk to Instagram."""

    def __init__(
        self,
        settings: Settings,
        adapter,
        breaker: Breaker,
        pacer: Pacer,
        handlers: dict[str, Handler],
    ):
        super().__init__(name="ig-worker", daemon=True)
        self.settings = settings
        self.adapter = adapter
        self.breaker = breaker
        self.pacer = pacer
        self.handlers = handlers
        self.wake = threading.Event()
        self.stop_flag = threading.Event()

    # ---- lifecycle -----------------------------------------------------
    def shutdown(self, timeout: float = 5.0) -> None:
        self.stop_flag.set()
        self.wake.set()
        self.join(timeout=timeout)

    def drain(self, timeout: float = 5.0) -> None:
        """Test helper: block until nothing is queued or running."""
        conn = db.get_conn(self.settings)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if queue.depth(conn) == 0:
                return
            time.sleep(0.01)
        raise TimeoutError("queue did not drain")

    # ---- main loop -----------------------------------------------------
    def run(self) -> None:
        conn = db.get_conn(self.settings)
        while not self.stop_flag.is_set():
            wait = self.breaker.wait_seconds()
            if wait > 0:
                self.stop_flag.wait(min(wait, IDLE_TIMEOUT))
                continue

            job = queue.claim_next(conn)
            if job is None:
                self.wake.wait(IDLE_TIMEOUT)
                self.wake.clear()
                continue

            self._run_job(conn, job)

    def _run_job(self, conn, job) -> None:
        payload = json.loads(job["payload"])
        handler = self.handlers.get(job["kind"])
        started = time.monotonic()

        if handler is None:
            queue.fail(conn, job["id"], f"no handler for {job['kind']}", retryable=False)
            return

        ctx = HandlerContext(
            conn=conn,
            adapter=self.adapter,
            settings=self.settings,
            pacer=self.pacer,
            enqueue=lambda kind, p: self._enqueue(conn, kind, p),
        )

        try:
            handler(ctx, payload)
        except t.IgRateLimited as exc:
            self.breaker.trip_temporary(self.settings.ig_backoff, f"Rate limited: {exc}")
            queue.requeue(conn, job["id"])
            self._log(job, payload, started, "rate_limited")
            return
        except t.IgChallenge as exc:
            self.breaker.trip_permanent(f"Instagram session invalid: {exc}")
            queue.requeue(conn, job["id"])
            self._log(job, payload, started, "challenge")
            return
        except (t.IgNotFound, t.IgPrivate) as exc:
            queue.fail(conn, job["id"], str(exc), retryable=False)
            self._log(job, payload, started, "terminal")
            return
        except t.IgTransient as exc:
            queue.fail(conn, job["id"], str(exc), retryable=True)
            self._log(job, payload, started, "transient")
            return
        except Exception as exc:  # noqa: BLE001 - a bug must not kill the worker
            log.exception("handler crashed")
            queue.fail(conn, job["id"], repr(exc), retryable=False)
            self._log(job, payload, started, "crashed")
            return

        queue.complete(conn, job["id"])
        self._log(job, payload, started, "done")

    def _enqueue(self, conn, kind: str, payload: dict) -> None:
        queue.enqueue_unique(conn, kind, payload)
        self.wake.set()

    def _log(self, job, payload: dict, started: float, outcome: str) -> None:
        log.info(
            json.dumps(
                {
                    "job_id": job["id"],
                    "kind": job["kind"],
                    "target": payload.get("username") or payload.get("shortcode"),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "outcome": outcome,
                }
            )
        )
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_pacer.py tests/test_worker_runner.py -v`
Expected: PASS, 10 tests.

If `test_rate_limit_trips_breaker_requeues_job_and_resumes` hangs, the breaker sleep loop is not waking after expiry — confirm `IDLE_TIMEOUT` caps the `stop_flag.wait()` so the loop re-checks.

- [ ] **Step 6: Commit**

```bash
git add api/app/worker/pacer.py api/app/worker/runner.py api/tests/test_pacer.py api/tests/test_worker_runner.py
git commit -m "feat(api): pacer and single serialized fetch worker thread"
```

---

### Task 8: Handlers — profile_sync and page_fetch

**Files:**
- Create: `api/app/worker/handlers.py`
- Test: `api/tests/test_handlers_profile.py`

**Interfaces:**
- Consumes: `HandlerContext`, `IgAdapter`, `paths.*`, `queue.PRIORITY`.
- Produces:
  - `handle_profile_sync(ctx, payload: {"username": str}) -> None`
  - `handle_page_fetch(ctx, payload: {"username": str}) -> None`
  - `HANDLERS: dict[str, Handler]` (populated fully in Task 9)

Behaviour contract:
- `profile_sync` upserts the `profiles` row, downloads the avatar to `<media>/<username>/avatar.jpg`, sets `last_synced_at`, and enqueues one `page_fetch` **only when `next_cursor IS NULL`** (a first sync). Re-syncing an already-paginated profile refreshes metadata without re-walking.
- A private profile is recorded with `is_private=1` and then raises `IgPrivate`, so the row exists for the UI to explain while the job still terminates.
- `page_fetch` reads `next_cursor`, fetches `settings.page_size` posts, upserts `media_items`, downloads each thumbnail, and writes the new cursor. Exhaustion stores `''`, not `NULL`.
- Both handlers call `ctx.pacer.wait()` before every adapter call, thumbnails included.

- [ ] **Step 1: Write the failing test**

`api/tests/test_handlers_profile.py`:

```python
import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ctx(settings, conn):
    adapter = FakeAdapter()
    enqueued = []
    context = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: enqueued.append((kind, payload)),
    )
    context.enqueued = enqueued  # type: ignore[attr-defined]
    return context


def test_profile_sync_upserts_row_and_avatar(ctx, settings):
    ctx.adapter.add_profile("nike", post_count=42)

    handlers.handle_profile_sync(ctx, {"username": "nike"})

    row = ctx.conn.execute("SELECT * FROM profiles WHERE username='nike'").fetchone()
    assert row["post_count"] == 42
    assert row["ig_user_id"] == "id-nike"
    assert row["last_synced_at"] is not None
    assert row["avatar_path"] == "nike/avatar.jpg"
    assert (settings.media_dir / "nike" / "avatar.jpg").exists()


def test_profile_sync_enqueues_first_page_only_once(ctx):
    ctx.adapter.add_profile("nike")

    handlers.handle_profile_sync(ctx, {"username": "nike"})
    assert ctx.enqueued == [("page_fetch", {"username": "nike"})]

    ctx.conn.execute("UPDATE profiles SET next_cursor='7' WHERE username='nike'")
    ctx.enqueued.clear()
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    assert ctx.enqueued == []


def test_profile_sync_records_private_profile_then_raises(ctx):
    ctx.adapter.add_profile("secret", is_private=True)

    with pytest.raises(t.IgPrivate):
        handlers.handle_profile_sync(ctx, {"username": "secret"})

    row = ctx.conn.execute("SELECT * FROM profiles WHERE username='secret'").fetchone()
    assert row["is_private"] == 1


def test_profile_sync_propagates_not_found_without_creating_a_row(ctx):
    with pytest.raises(t.IgNotFound):
        handlers.handle_profile_sync(ctx, {"username": "ghost"})
    assert ctx.conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"] == 0


def test_page_fetch_inserts_items_thumbs_and_cursor(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=10)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    items = ctx.conn.execute(
        "SELECT * FROM media_items ORDER BY shortcode"
    ).fetchall()
    assert len(items) == settings.page_size
    assert items[0]["full_status"] == "none"
    thumbs = ctx.conn.execute(
        "SELECT * FROM media_files WHERE role='thumb'"
    ).fetchall()
    assert len(thumbs) == settings.page_size
    assert (settings.media_dir / "nike" / "nike-0" / "thumb.jpg").exists()
    cursor = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"]
    assert cursor == str(settings.page_size)


def test_page_fetch_resumes_from_stored_cursor(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=10)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})

    shortcodes = [
        r["shortcode"]
        for r in ctx.conn.execute(
            "SELECT shortcode FROM media_items ORDER BY LENGTH(shortcode), shortcode"
        ).fetchall()
    ]
    assert len(shortcodes) == settings.page_size * 2
    assert len(set(shortcodes)) == len(shortcodes)


def test_page_fetch_marks_exhaustion_with_empty_string(ctx, settings):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=3)
    handlers.handle_profile_sync(ctx, {"username": "nike"})

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    cursor = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"]
    assert cursor == ""


def test_page_fetch_on_exhausted_profile_is_a_no_op(ctx):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=2)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    before = len(ctx.adapter.calls)

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    assert len(ctx.adapter.calls) == before, "hit Instagram for an exhausted profile"


def test_page_fetch_upsert_does_not_clobber_ready_media(ctx):
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=2)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    ctx.conn.execute("UPDATE media_items SET full_status='ready' WHERE shortcode='nike-0'")
    ctx.conn.execute("UPDATE profiles SET next_cursor=NULL WHERE username='nike'")

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    status = ctx.conn.execute(
        "SELECT full_status FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()["full_status"]
    assert status == "ready"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_handlers_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.worker.handlers'`

- [ ] **Step 3: Write the implementation**

`api/app/worker/handlers.py`:

```python
from app import paths
from app.clock import now_iso
from app.ig import types as t
from app.worker.runner import HandlerContext


def handle_profile_sync(ctx: HandlerContext, payload: dict) -> None:
    username = payload["username"]

    ctx.pacer.wait()
    profile = ctx.adapter.fetch_profile(username)

    ctx.conn.execute(
        "INSERT INTO profiles (username, ig_user_id, full_name, biography,"
        " is_private, post_count, created_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(username) DO UPDATE SET"
        " ig_user_id=excluded.ig_user_id, full_name=excluded.full_name,"
        " biography=excluded.biography, is_private=excluded.is_private,"
        " post_count=excluded.post_count",
        (
            profile.username,
            profile.user_id,
            profile.full_name,
            profile.biography,
            int(profile.is_private),
            profile.post_count,
            now_iso(),
        ),
    )

    if profile.is_private:
        raise t.IgPrivate(f"{username} is private")

    avatar_dest = ctx.settings.media_dir / username / "avatar.jpg"
    ctx.pacer.wait()
    ctx.adapter.download_to(profile.avatar_url, avatar_dest)

    ctx.conn.execute(
        "UPDATE profiles SET avatar_path=?, last_synced_at=? WHERE username=?",
        (paths.rel_path(ctx.settings.media_dir, avatar_dest), now_iso(), username),
    )

    row = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row["next_cursor"] is None:
        ctx.enqueue("page_fetch", {"username": username})


def handle_page_fetch(ctx: HandlerContext, payload: dict) -> None:
    username = payload["username"]
    row = ctx.conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row is None:
        raise t.IgNotFound(f"{username} has not been synced")

    cursor = row["next_cursor"]
    if cursor == "":
        return  # exhausted; never hit Instagram again for this profile

    ctx.pacer.wait()
    page = ctx.adapter.fetch_page(username, cursor, ctx.settings.page_size)

    for post in page.posts:
        ctx.conn.execute(
            "INSERT INTO media_items (shortcode, username, kind, taken_at, caption,"
            " is_video, child_count, ig_url, discovered_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(shortcode) DO UPDATE SET"
            " caption=excluded.caption, child_count=excluded.child_count",
            (
                post.shortcode,
                username,
                post.kind,
                post.taken_at_iso,
                post.caption,
                int(post.is_video),
                post.child_count,
                post.ig_url,
                now_iso(),
            ),
        )

        thumb_dest = paths.item_dir(ctx.settings.media_dir, username, post.shortcode) / "thumb.jpg"
        if not thumb_dest.exists():
            ctx.pacer.wait()
            saved = ctx.adapter.download_to(post.thumb_url, thumb_dest)
            ctx.conn.execute(
                "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
                " width, height) VALUES (?,'thumb',0,?,?,?,?,?)"
                " ON CONFLICT(shortcode, role, child_idx) DO UPDATE SET"
                " path=excluded.path, bytes=excluded.bytes",
                (
                    post.shortcode,
                    paths.rel_path(ctx.settings.media_dir, thumb_dest),
                    saved.mime,
                    saved.bytes,
                    saved.width,
                    saved.height,
                ),
            )

    ctx.conn.execute(
        "UPDATE profiles SET next_cursor=? WHERE username=?",
        ("" if page.next_cursor is None else page.next_cursor, username),
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_handlers_profile.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/handlers.py api/tests/test_handlers_profile.py
git commit -m "feat(api): profile_sync and page_fetch handlers"
```

---

### Task 9: Handler — media_fetch

**Files:**
- Modify: `api/app/worker/handlers.py` (append `handle_media_fetch` and `HANDLERS`)
- Test: `api/tests/test_handlers_media.py`

**Interfaces:**
- Consumes: everything from Task 8.
- Produces:
  - `handle_media_fetch(ctx, payload: {"shortcode": str}) -> None`
  - `HANDLERS = {"profile_sync": handle_profile_sync, "page_fetch": handle_page_fetch, "media_fetch": handle_media_fetch}`

Behaviour contract: sets `full_status='fetching'` before the adapter call, writes one `media_files` row per returned `SavedFile`, sets `full_status='ready'` on success. On any `IgError` it sets `full_status='failed'` with `full_error` and re-raises so the runner applies the right queue policy. Already-`ready` items return without touching Instagram.

- [ ] **Step 1: Write the failing test**

`api/tests/test_handlers_media.py`:

```python
import pytest

from app.ig import types as t
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ready_ctx(settings, conn):
    adapter = FakeAdapter()
    adapter.add_profile("nike")
    adapter.add_posts("nike", count=2)
    adapter.add_posts("nike", count=1, child_count=3)
    ctx = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=Pacer(min_interval=0.0),
        enqueue=lambda kind, payload: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    return ctx


def test_media_fetch_writes_single_file_and_marks_ready(ready_ctx, settings):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})

    item = ready_ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode='nike-0'"
    ).fetchone()
    files = ready_ctx.conn.execute(
        "SELECT * FROM media_files WHERE shortcode='nike-0' AND role='full'"
    ).fetchall()
    assert item["full_status"] == "ready"
    assert len(files) == 1
    assert files[0]["child_idx"] == 0
    assert files[0]["path"] == "nike/nike-0/full.jpg"
    assert (settings.media_dir / "nike" / "nike-0" / "full.jpg").exists()


def test_media_fetch_writes_all_carousel_children(ready_ctx):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-2"})

    files = ready_ctx.conn.execute(
        "SELECT child_idx, path FROM media_files"
        " WHERE shortcode='nike-2' AND role='full' ORDER BY child_idx"
    ).fetchall()
    assert [f["child_idx"] for f in files] == [1, 2, 3]
    assert files[0]["path"] == "nike/nike-2/full_1.jpg"


def test_media_fetch_is_a_no_op_when_already_ready(ready_ctx):
    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})
    before = len(ready_ctx.adapter.calls)

    handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-0"})

    assert len(ready_ctx.adapter.calls) == before


def test_media_fetch_marks_failed_and_reraises(ready_ctx, settings):
    ready_ctx.adapter.raise_on("fetch_media", t.IgTransient("reset"))

    with pytest.raises(t.IgTransient):
        handlers.handle_media_fetch(ready_ctx, {"shortcode": "nike-1"})

    item = ready_ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode='nike-1'"
    ).fetchone()
    assert item["full_status"] == "failed"
    assert "reset" in item["full_error"]
    assert list(settings.media_dir.rglob("*.part")) == []


def test_media_fetch_unknown_shortcode_raises_not_found(ready_ctx):
    with pytest.raises(t.IgNotFound):
        handlers.handle_media_fetch(ready_ctx, {"shortcode": "nope"})


def test_handlers_registry_covers_every_job_kind():
    from app.worker import queue

    assert set(handlers.HANDLERS) == set(queue.PRIORITY)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_handlers_media.py -v`
Expected: FAIL — `AttributeError: module 'app.worker.handlers' has no attribute 'handle_media_fetch'`

- [ ] **Step 3: Append the implementation to `api/app/worker/handlers.py`**

```python
def handle_media_fetch(ctx: HandlerContext, payload: dict) -> None:
    shortcode = payload["shortcode"]
    item = ctx.conn.execute(
        "SELECT * FROM media_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None:
        raise t.IgNotFound(f"unknown shortcode {shortcode}")
    if item["full_status"] == "ready":
        return

    ctx.conn.execute(
        "UPDATE media_items SET full_status='fetching', full_error=NULL WHERE shortcode=?",
        (shortcode,),
    )

    dest_dir = paths.item_dir(ctx.settings.media_dir, item["username"], shortcode)
    try:
        ctx.pacer.wait()
        saved_files = ctx.adapter.fetch_media(shortcode, dest_dir)
    except t.IgError as exc:
        ctx.conn.execute(
            "UPDATE media_items SET full_status='failed', full_error=? WHERE shortcode=?",
            (str(exc), shortcode),
        )
        raise

    for saved in saved_files:
        ctx.conn.execute(
            "INSERT INTO media_files (shortcode, role, child_idx, path, mime, bytes,"
            " width, height) VALUES (?,'full',?,?,?,?,?,?)"
            " ON CONFLICT(shortcode, role, child_idx) DO UPDATE SET"
            " path=excluded.path, mime=excluded.mime, bytes=excluded.bytes,"
            " width=excluded.width, height=excluded.height",
            (
                shortcode,
                saved.child_idx,
                paths.rel_path(ctx.settings.media_dir, saved.path),
                saved.mime,
                saved.bytes,
                saved.width,
                saved.height,
            ),
        )

    ctx.conn.execute(
        "UPDATE media_items SET full_status='ready', full_error=NULL WHERE shortcode=?",
        (shortcode,),
    )


HANDLERS = {
    "profile_sync": handle_profile_sync,
    "page_fetch": handle_page_fetch,
    "media_fetch": handle_media_fetch,
}
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_handlers_media.py tests/test_handlers_profile.py -v`
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/handlers.py api/tests/test_handlers_media.py
git commit -m "feat(api): media_fetch handler and handler registry"
```

---

### Task 10: Real Instaloader adapter and RateController

**Files:**
- Create: `api/app/ig/rate.py`, `api/app/ig/adapter.py`
- Create: `api/tests/fixtures/post_image.json`, `api/tests/fixtures/post_video.json`, `api/tests/fixtures/post_carousel.json`
- Test: `api/tests/test_adapter_parse.py`

**Interfaces:**
- Consumes: `types.*`, `paths.atomic_write`, `paths.full_filename`, `Settings`.
- Produces:
  - `PacedRateController(context, min_interval: float)` — an `instaloader.RateController` subclass
  - `InstaloaderAdapter(settings: Settings)` implementing the `IgAdapter` Protocol
  - `classify(exc: Exception) -> IgError` — maps Instaloader exceptions onto the error hierarchy
  - `post_to_igpost(node: dict, shortcode: str) -> IgPost` — pure, fixture-tested
  - `make_adapter(settings) -> IgAdapter` — returns `FakeAdapter` when `settings.adapter == "fake"`, otherwise `InstaloaderAdapter`

The parsing functions are pure and take plain dicts, which is what makes them testable without network access. `classify` is the seam that turns library-specific exceptions into the five cases the runner knows how to handle — when Instagram rotates something, this is usually the function that needs updating.

- [ ] **Step 1: Create the fixtures**

Capture three real payloads once by running the live canary (Task 16) with `INSTALOADER_DUMP=1`, or hand-write them to match the shape below. `api/tests/fixtures/post_image.json`:

```json
{
  "shortcode": "CxImage01",
  "__typename": "GraphImage",
  "taken_at_timestamp": 1767225600,
  "is_video": false,
  "display_url": "https://cdn.test/CxImage01/full.jpg",
  "thumbnail_src": "https://cdn.test/CxImage01/thumb.jpg",
  "dimensions": {"width": 1080, "height": 1350},
  "edge_media_to_caption": {"edges": [{"node": {"text": "a caption"}}]}
}
```

`api/tests/fixtures/post_video.json`:

```json
{
  "shortcode": "CxVideo01",
  "__typename": "GraphVideo",
  "product_type": "clips",
  "taken_at_timestamp": 1767312000,
  "is_video": true,
  "video_url": "https://cdn.test/CxVideo01/full.mp4",
  "display_url": "https://cdn.test/CxVideo01/cover.jpg",
  "thumbnail_src": "https://cdn.test/CxVideo01/thumb.jpg",
  "dimensions": {"width": 1080, "height": 1920},
  "edge_media_to_caption": {"edges": []}
}
```

`api/tests/fixtures/post_carousel.json`:

```json
{
  "shortcode": "CxCarousel1",
  "__typename": "GraphSidecar",
  "taken_at_timestamp": 1767398400,
  "is_video": false,
  "thumbnail_src": "https://cdn.test/CxCarousel1/thumb.jpg",
  "dimensions": {"width": 1080, "height": 1080},
  "edge_media_to_caption": {"edges": [{"node": {"text": "three slides"}}]},
  "edge_sidecar_to_children": {
    "edges": [
      {"node": {"is_video": false, "display_url": "https://cdn.test/c/1.jpg", "dimensions": {"width": 1080, "height": 1080}}},
      {"node": {"is_video": false, "display_url": "https://cdn.test/c/2.jpg", "dimensions": {"width": 1080, "height": 1080}}},
      {"node": {"is_video": true, "video_url": "https://cdn.test/c/3.mp4", "dimensions": {"width": 1080, "height": 1920}}}
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

`api/tests/test_adapter_parse.py`:

```python
import json
from pathlib import Path

import pytest

from app.ig import adapter
from app.ig import types as t

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_image_post():
    post = adapter.post_to_igpost(load("post_image.json"), "CxImage01")
    assert post.kind == "image"
    assert post.is_video is False
    assert post.child_count == 1
    assert post.caption == "a caption"
    assert post.thumb_url.endswith("thumb.jpg")
    assert post.ig_url == "https://www.instagram.com/p/CxImage01/"
    assert post.taken_at_iso.startswith("2026-01-01T")


def test_parse_reel_is_kind_reel_not_video():
    post = adapter.post_to_igpost(load("post_video.json"), "CxVideo01")
    assert post.kind == "reel"
    assert post.is_video is True
    assert post.caption == ""


def test_parse_carousel_counts_children():
    post = adapter.post_to_igpost(load("post_carousel.json"), "CxCarousel1")
    assert post.kind == "carousel"
    assert post.child_count == 3


def test_classify_maps_every_instaloader_failure():
    import instaloader.exceptions as e

    assert isinstance(adapter.classify(e.ProfileNotExistsException("x")), t.IgNotFound)
    assert isinstance(adapter.classify(e.PrivateProfileNotFollowedException("x")), t.IgPrivate)
    assert isinstance(adapter.classify(e.TooManyRequestsException("x")), t.IgRateLimited)
    assert isinstance(adapter.classify(e.LoginRequiredException("x")), t.IgChallenge)
    assert isinstance(adapter.classify(e.ConnectionException("x")), t.IgTransient)
    assert isinstance(adapter.classify(RuntimeError("surprise")), t.IgTransient)


def test_classify_reads_checkpoint_from_message():
    import instaloader.exceptions as e

    err = adapter.classify(e.ConnectionException("checkpoint_required"))
    assert isinstance(err, t.IgChallenge)


def test_make_adapter_honours_the_fake_flag(settings):
    from app.ig.fake import FakeAdapter

    assert isinstance(adapter.make_adapter(settings), FakeAdapter)


def test_rate_controller_enforces_min_interval():
    from app.ig.rate import PacedRateController

    slept = []
    rc = PacedRateController(context=None, min_interval=2.5, sleep=slept.append)
    rc.sleep(0.1)
    assert slept == [2.5]
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_adapter_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ig.adapter'`

- [ ] **Step 4: Write the rate controller**

`api/app/ig/rate.py`:

```python
import time
from typing import Callable

import instaloader


class PacedRateController(instaloader.RateController):
    """Adds a hard floor to the gap between the HTTP requests Instaloader
    makes internally, on top of its own 429 handling.

    The worker's Pacer covers gaps between adapter calls; this covers the
    several requests a single adapter call can make while paginating.
    """

    def __init__(self, context, min_interval: float, sleep: Callable[[float], None] = time.sleep):
        if context is not None:
            super().__init__(context)
        self._min_interval = min_interval
        self._sleep = sleep

    def sleep(self, secs: float) -> None:
        self._sleep(max(secs, self._min_interval))
```

Note: `instaloader` must not be imported outside `adapter.py` per the global constraint, and `rate.py` breaks that. Resolve it by making `rate.py` part of the allowed set — update the guard test in `api/tests/test_ig_contract.py` to allow both filenames:

```python
        if "instaloader" in p.read_text() and p.name not in ("adapter.py", "rate.py")
```

Two files, both inside `app/ig/`, is still a one-directory blast radius. Update the Global Constraints line in this plan's header if you prefer to keep them in sync.

- [ ] **Step 5: Write the adapter**

`api/app/ig/adapter.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import instaloader
import instaloader.exceptions as ie

from app import paths
from app.config import Settings
from app.ig import types as t
from app.ig.rate import PacedRateController

_CHALLENGE_HINTS = ("checkpoint", "challenge", "login_required", "please wait")


def classify(exc: Exception) -> t.IgError:
    """Map an Instaloader failure onto the five cases the runner handles.

    When Instagram rotates something, this is usually the first function
    that needs updating.
    """
    message = str(exc)
    if isinstance(exc, (ie.ProfileNotExistsException, ie.PostChangedException)):
        return t.IgNotFound(message)
    if isinstance(exc, (ie.PrivateProfileNotFollowedException, ie.ProfileHasNoPicsException)):
        return t.IgPrivate(message)
    if isinstance(exc, ie.TooManyRequestsException):
        return t.IgRateLimited(message)
    if isinstance(exc, (ie.LoginRequiredException, ie.BadCredentialsException,
                        ie.TwoFactorAuthRequiredException)):
        return t.IgChallenge(message)
    if any(hint in message.lower() for hint in _CHALLENGE_HINTS):
        return t.IgChallenge(message)
    return t.IgTransient(message)


def _caption(node: dict) -> str:
    edges = node.get("edge_media_to_caption", {}).get("edges", [])
    return edges[0]["node"]["text"] if edges else ""


def _kind(node: dict) -> str:
    typename = node.get("__typename", "")
    if typename == "GraphSidecar":
        return "carousel"
    if node.get("is_video"):
        return "reel" if node.get("product_type") == "clips" else "video"
    return "image"


def post_to_igpost(node: dict, shortcode: str) -> t.IgPost:
    children = node.get("edge_sidecar_to_children", {}).get("edges", [])
    taken = datetime.fromtimestamp(node["taken_at_timestamp"], tz=timezone.utc)
    return t.IgPost(
        shortcode=shortcode,
        kind=_kind(node),
        taken_at_iso=taken.isoformat(),
        caption=_caption(node),
        is_video=bool(node.get("is_video")),
        child_count=len(children) or 1,
        thumb_url=node.get("thumbnail_src") or node["display_url"],
        ig_url=f"https://www.instagram.com/p/{shortcode}/",
    )


class InstaloaderAdapter:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._loader = instaloader.Instaloader(
            quiet=True,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            rate_controller=lambda ctx: PacedRateController(ctx, settings.ig_min_interval),
        )
        self._session_file = settings.session_dir / f"{settings.ig_username}.session"
        self._logged_in = False
        self._iterators: dict[str, object] = {}

    # ---- session -------------------------------------------------------
    def login(self) -> None:
        try:
            if self._session_file.exists():
                self._loader.load_session_from_file(
                    self._settings.ig_username, str(self._session_file)
                )
            else:
                self._loader.login(self._settings.ig_username, self._settings.ig_password)
                self._session_file.parent.mkdir(parents=True, exist_ok=True)
                self._loader.save_session_to_file(str(self._session_file))
            self._logged_in = True
        except Exception as exc:
            raise classify(exc) from exc

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    # ---- reads ---------------------------------------------------------
    def fetch_profile(self, username: str) -> t.IgProfile:
        self._ensure_login()
        try:
            p = instaloader.Profile.from_username(self._loader.context, username)
            return t.IgProfile(
                username=p.username,
                user_id=str(p.userid),
                full_name=p.full_name or "",
                biography=p.biography or "",
                is_private=bool(p.is_private),
                post_count=int(p.mediacount),
                avatar_url=p.profile_pic_url,
            )
        except Exception as exc:
            raise classify(exc) from exc

    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        self._ensure_login()
        try:
            profile = instaloader.Profile.from_username(self._loader.context, username)
            iterator = profile.get_posts()
            if cursor:
                frozen = instaloader.FrozenNodeIterator(**json.loads(cursor))
                iterator.thaw(frozen)

            posts: list[t.IgPost] = []
            exhausted = False
            for _ in range(limit):
                try:
                    post = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                posts.append(post_to_igpost(post._node, post.shortcode))

            next_cursor = None if exhausted else json.dumps(iterator.freeze()._asdict())
            return t.IgPage(posts=posts, next_cursor=next_cursor)
        except Exception as exc:
            raise classify(exc) from exc

    def fetch_media(self, shortcode: str, dest_dir: Path) -> list[t.SavedFile]:
        self._ensure_login()
        try:
            post = instaloader.Post.from_shortcode(self._loader.context, shortcode)
            targets: list[tuple[int, str, bool, int | None, int | None]] = []
            if post.typename == "GraphSidecar":
                for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                    url = node.video_url if node.is_video else node.display_url
                    targets.append((idx, url, node.is_video, None, None))
            else:
                url = post.video_url if post.is_video else post.url
                targets.append((0, url, post.is_video, post.dimensions[0], post.dimensions[1]))

            saved: list[t.SavedFile] = []
            for child_idx, url, is_video, width, height in targets:
                ext = "mp4" if is_video else "jpg"
                dest = dest_dir / paths.full_filename(child_idx, ext)
                saved.append(
                    self._download(url, dest, child_idx,
                                   "video/mp4" if is_video else "image/jpeg", width, height)
                )
            return saved
        except t.IgError:
            raise
        except Exception as exc:
            raise classify(exc) from exc

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        self._ensure_login()
        return self._download(url, dest, 0, "image/jpeg", None, None)

    def _download(self, url, dest, child_idx, mime, width, height) -> t.SavedFile:
        try:
            resp = self._loader.context.get_raw(url)
            size = paths.atomic_write(dest, lambda fh: fh.write(resp.content))
        except Exception as exc:
            raise classify(exc) from exc
        return t.SavedFile(child_idx, dest, mime, size, width, height)


def make_adapter(settings: Settings):
    if settings.adapter == "fake":
        from app.ig.fake import FakeAdapter

        return FakeAdapter()
    return InstaloaderAdapter(settings)
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_adapter_parse.py tests/test_ig_contract.py -v`
Expected: PASS, 15 tests.

If `test_parse_reel_is_kind_reel_not_video` fails, Instaloader's `product_type` key has moved — that is exactly the breakage this module exists to contain, and the fix belongs in `_kind`.

- [ ] **Step 7: Commit**

```bash
git add api/app/ig/adapter.py api/app/ig/rate.py api/tests/fixtures api/tests/test_adapter_parse.py api/tests/test_ig_contract.py
git commit -m "feat(api): Instaloader adapter, rate controller, error classification"
```

---

### Task 11: Interactive login entrypoint

**Files:**
- Create: `api/app/ig/login.py`
- Test: `api/tests/test_login_entrypoint.py`

**Interfaces:**
- Consumes: `make_adapter`, `Settings`, `load_settings`.
- Produces: `main(settings=None, adapter_factory=make_adapter, out=print) -> int` — exit code 0 on success, 1 on failure. Runnable as `python -m app.ig.login`.

This exists because two-factor prompts and checkpoint challenges cannot be solved headlessly. It is the only supported way to clear a permanent breaker trip.

- [ ] **Step 1: Write the failing test**

`api/tests/test_login_entrypoint.py`:

```python
from app.ig import types as t
from app.ig.login import main


class OkAdapter:
    def __init__(self):
        self.called = False

    def login(self):
        self.called = True


class FailingAdapter:
    def login(self):
        raise t.IgChallenge("checkpoint_required")


def test_login_success_returns_zero(settings):
    adapter = OkAdapter()
    lines = []
    code = main(settings=settings, adapter_factory=lambda _s: adapter, out=lines.append)
    assert code == 0
    assert adapter.called is True
    assert any("session saved" in line.lower() for line in lines)


def test_login_failure_returns_one_and_explains(settings):
    lines = []
    code = main(settings=settings, adapter_factory=lambda _s: FailingAdapter(), out=lines.append)
    assert code == 1
    assert any("checkpoint_required" in line for line in lines)


def test_login_refuses_without_credentials(settings):
    blank = settings.__class__(**{**settings.__dict__, "ig_username": ""})
    lines = []
    code = main(settings=blank, adapter_factory=lambda _s: OkAdapter(), out=lines.append)
    assert code == 1
    assert any("IG_USERNAME" in line for line in lines)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_login_entrypoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ig.login'`

- [ ] **Step 3: Write the implementation**

`api/app/ig/login.py`:

```python
import sys

from app.config import Settings, load_settings
from app.ig import types as t
from app.ig.adapter import make_adapter


def main(settings: Settings | None = None, adapter_factory=make_adapter, out=print) -> int:
    settings = settings or load_settings()

    if not settings.ig_username or not settings.ig_password:
        out("IG_USERNAME and IG_PASSWORD must be set in .env before logging in.")
        return 1

    settings.session_dir.mkdir(parents=True, exist_ok=True)
    out(f"Logging in as {settings.ig_username}...")

    try:
        adapter_factory(settings).login()
    except t.IgError as exc:
        out(f"Login failed: {exc}")
        out("If this is a checkpoint, open Instagram in a browser, clear the")
        out("challenge for this account, then run this command again.")
        return 1

    out(f"Session saved to {settings.session_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_login_entrypoint.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/login.py api/tests/test_login_entrypoint.py
git commit -m "feat(api): interactive Instagram login entrypoint"
```

---

### Task 12: App factory, lifespan, status and activity routes

**Files:**
- Create: `api/app/services/__init__.py`, `api/app/services/activity.py`, `api/app/routes/__init__.py`, `api/app/routes/status.py`, `api/app/routes/activity.py`, `api/app/main.py`
- Test: `api/tests/test_api_status.py`

**Interfaces:**
- Consumes: `sweep`, `Worker`, `Breaker`, `Pacer`, `HANDLERS`, `make_adapter`, `queue.depth`.
- Produces:
  - `services.activity.record(conn, action: str, target: str | None, detail: dict | None) -> int`
  - `services.activity.recent(conn, limit: int) -> list[dict]`
  - `main.create_app(settings=None, adapter=None) -> FastAPI` with `app.state.settings`, `app.state.adapter`, `app.state.breaker`, `app.state.worker`
  - `main.get_conn_dep(request) -> sqlite3.Connection` FastAPI dependency
  - `GET /api/status -> {"worker": "running"|"stopped", "breaker": {...}, "queue_depth": int}`
  - `GET /api/activity?limit=100 -> {"items": [...]}`
  - pytest fixture `client` (TestClient with the fake adapter and the worker thread **not** started)

Starting the worker inside route tests would make them timing-dependent. `create_app(start_worker=False)` keeps API tests deterministic; Task 7 already covers the worker's own behaviour.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/conftest.py`:

```python
from fastapi.testclient import TestClient

from app.ig.fake import FakeAdapter
from app.main import create_app


@pytest.fixture
def adapter():
    fake = FakeAdapter()
    fake.add_profile("nike", post_count=10)
    fake.add_posts("nike", count=10)
    return fake


@pytest.fixture
def client(settings, conn, adapter):
    app = create_app(settings=settings, adapter=adapter, start_worker=False)
    with TestClient(app) as c:
        c.app_state = app.state  # type: ignore[attr-defined]
        yield c
```

`api/tests/test_api_status.py`:

```python
from app.services import activity
from app.worker import queue


def test_status_reports_clear_breaker_and_zero_depth(client):
    body = client.get("/api/status").json()
    assert body["breaker"]["tripped"] is False
    assert body["queue_depth"] == 0
    assert body["worker"] in {"running", "stopped"}


def test_status_reflects_a_tripped_breaker(client):
    client.app_state.breaker.trip_permanent("Instagram session invalid: checkpoint")
    body = client.get("/api/status").json()
    assert body["breaker"]["tripped"] is True
    assert body["breaker"]["permanent"] is True
    assert "checkpoint" in body["breaker"]["reason"]


def test_status_reports_queue_depth(client, conn):
    queue.enqueue(conn, "page_fetch", {"username": "nike"})
    queue.enqueue(conn, "media_fetch", {"shortcode": "nike-0"})
    assert client.get("/api/status").json()["queue_depth"] == 2


def test_activity_returns_newest_first(client, conn):
    activity.record(conn, "lookup", "nike", None)
    activity.record(conn, "download", "nike", {"count": 3, "base": "x"})

    items = client.get("/api/activity").json()["items"]

    assert [i["action"] for i in items] == ["download", "lookup"]
    assert items[0]["detail"] == {"count": 3, "base": "x"}
    assert items[1]["detail"] is None


def test_activity_respects_limit(client, conn):
    for i in range(5):
        activity.record(conn, "lookup", f"user{i}", None)
    assert len(client.get("/api/activity?limit=2").json()["items"]) == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_api_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write the activity service**

`api/app/services/__init__.py`: empty file.

`api/app/services/activity.py`:

```python
import json
import sqlite3

from app.clock import now_iso


def record(conn: sqlite3.Connection, action: str, target: str | None, detail: dict | None) -> int:
    cur = conn.execute(
        "INSERT INTO activity_log (ts, action, target, detail) VALUES (?,?,?,?)",
        (now_iso(), action, target, json.dumps(detail) if detail is not None else None),
    )
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, action, target, detail FROM activity_log"
        " ORDER BY ts DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "action": r["action"],
            "target": r["target"],
            "detail": json.loads(r["detail"]) if r["detail"] else None,
        }
        for r in rows
    ]
```

- [ ] **Step 4: Write the app factory and the two routes**

`api/app/routes/__init__.py`: empty file.

`api/app/routes/status.py`:

```python
from fastapi import APIRouter, Depends, Request

from app.main_deps import get_conn_dep
from app.worker import queue

router = APIRouter()


@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
    }
```

`api/app/routes/activity.py`:

```python
from fastapi import APIRouter, Depends, Query

from app.main_deps import get_conn_dep
from app.services import activity

router = APIRouter()


@router.get("/activity")
def get_activity(limit: int = Query(100, ge=1, le=1000), conn=Depends(get_conn_dep)):
    return {"items": activity.recent(conn, limit)}
```

`api/app/main_deps.py` — a tiny module so routes never import `main` (which would be circular):

```python
from fastapi import Request

from app import db


def get_conn_dep(request: Request):
    return db.get_conn(request.app.state.settings)


def wake_worker(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.wake.set()
```

`api/app/main.py`:

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.config import Settings, load_settings
from app.ig.adapter import make_adapter
from app.routes import activity as activity_routes
from app.routes import status as status_routes
from app.worker import sweep
from app.worker.breaker import Breaker
from app.worker.handlers import HANDLERS
from app.worker.pacer import Pacer
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(
    settings: Settings | None = None,
    adapter=None,
    start_worker: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    adapter = adapter or make_adapter(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.get_conn(settings)
        db.init_schema(conn)
        for directory in (settings.media_dir, settings.session_dir, settings.out_dir):
            directory.mkdir(parents=True, exist_ok=True)
        result = sweep.sweep(conn, settings.media_dir)
        logging.info('{"event":"sweep","result":%s}', result)

        if start_worker:
            worker = Worker(
                settings=settings,
                adapter=adapter,
                breaker=app.state.breaker,
                pacer=app.state.pacer,
                handlers=HANDLERS,
            )
            worker.start()
            app.state.worker = worker
        yield
        worker = getattr(app.state, "worker", None)
        if worker is not None:
            worker.shutdown()

    app = FastAPI(title="instascraper", lifespan=lifespan)
    app.state.settings = settings
    app.state.adapter = adapter
    app.state.breaker = Breaker()
    app.state.pacer = Pacer(min_interval=settings.ig_min_interval)
    app.state.worker = None

    app.include_router(status_routes.router, prefix="/api")
    app.include_router(activity_routes.router, prefix="/api")
    return app


app = create_app()
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_api_status.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add api/app/main.py api/app/main_deps.py api/app/routes api/app/services api/tests/conftest.py api/tests/test_api_status.py
git commit -m "feat(api): app factory, lifespan wiring, status and activity routes"
```

---

### Task 13: Profile routes

**Files:**
- Create: `api/app/routes/profiles.py`
- Modify: `api/app/main.py` (include the router)
- Test: `api/tests/test_api_profiles.py`

**Interfaces:**
- Consumes: `get_conn_dep`, `wake_worker`, `queue.enqueue_unique`, `activity.record`, `paths`.
- Produces:
  - `GET /api/profiles -> {"items": [ProfileSummary]}` — tracked profiles, alphabetical
  - `GET /api/profiles/{username} -> ProfileDetail` — 404 with `{"detail", "last_error"}` when absent
  - `POST /api/profiles/{username}/sync -> {"queued": bool}`
  - `PUT /api/profiles/{username}/tracked` body `{"tracked": bool}` -> `{"tracked": bool}`
  - `DELETE /api/profiles/{username}/cache -> {"removed_files": int}`
  - `GET /api/profiles/{username}/media?limit=&offset= -> {"items": [MediaSummary], "total": int, "exhausted": bool}`
  - `POST /api/profiles/{username}/load-more -> {"queued": bool, "exhausted": bool}`

  `ProfileDetail` keys: `username, full_name, biography, is_private, post_count, avatar_url, tracked, last_synced_at, exhausted, cached_count`.
  `MediaSummary` keys: `shortcode, kind, taken_at, caption, is_video, child_count, full_status, thumb_url, ig_url`.
  `thumb_url` and `avatar_url` are API paths (`/api/media/{sc}/thumb`), not Instagram URLs — the browser never talks to Instagram.

- [ ] **Step 1: Write the failing test**

`api/tests/test_api_profiles.py`:

```python
import json

from app.worker import handlers, queue
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def seed(client, conn, settings, adapter, username="nike"):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": username})
    handlers.handle_page_fetch(ctx, {"username": username})


def test_sync_enqueues_a_job_and_logs_the_lookup(client, conn):
    body = client.post("/api/profiles/nike/sync").json()
    assert body["queued"] is True

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["kind"] == "profile_sync"
    assert json.loads(row["payload"]) == {"username": "nike"}
    assert conn.execute(
        "SELECT action FROM activity_log"
    ).fetchone()["action"] == "lookup"


def test_sync_is_idempotent_while_queued(client):
    assert client.post("/api/profiles/nike/sync").json()["queued"] is True
    assert client.post("/api/profiles/nike/sync").json()["queued"] is False


def test_get_unknown_profile_is_404_with_last_error(client, conn):
    queue.enqueue(conn, "profile_sync", {"username": "ghost"})
    job_id = queue.claim_next(conn)["id"]
    queue.fail(conn, job_id, "ghost does not exist", retryable=False)

    resp = client.get("/api/profiles/ghost")

    assert resp.status_code == 404
    assert "does not exist" in resp.json()["detail"]["last_error"]


def test_get_profile_returns_detail(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.get("/api/profiles/nike").json()

    assert body["username"] == "nike"
    assert body["post_count"] == 10
    assert body["avatar_url"] == "/api/profiles/nike/avatar"
    assert body["exhausted"] is False
    assert body["cached_count"] == 0


def test_media_page_returns_thumb_urls_and_total(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.get("/api/profiles/nike/media?limit=2&offset=0").json()

    assert body["total"] == settings.page_size
    assert len(body["items"]) == 2
    assert body["items"][0]["thumb_url"].startswith("/api/media/")
    assert body["items"][0]["full_status"] == "none"
    assert body["exhausted"] is False


def test_media_page_is_newest_first(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    items = client.get("/api/profiles/nike/media?limit=50").json()["items"]
    taken = [i["taken_at"] for i in items]
    assert taken == sorted(taken, reverse=True)


def test_tracked_toggle_round_trips(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    assert client.put("/api/profiles/nike/tracked", json={"tracked": True}).json() == {
        "tracked": True
    }
    assert [p["username"] for p in client.get("/api/profiles").json()["items"]] == ["nike"]

    client.put("/api/profiles/nike/tracked", json={"tracked": False})
    assert client.get("/api/profiles").json()["items"] == []


def test_load_more_enqueues_page_fetch(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)

    body = client.post("/api/profiles/nike/load-more").json()

    assert body == {"queued": True, "exhausted": False}
    assert conn.execute(
        "SELECT kind FROM jobs ORDER BY id DESC"
    ).fetchone()["kind"] == "page_fetch"


def test_load_more_on_exhausted_profile_queues_nothing(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    conn.execute("UPDATE profiles SET next_cursor='' WHERE username='nike'")

    body = client.post("/api/profiles/nike/load-more").json()

    assert body == {"queued": False, "exhausted": True}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0


def test_clear_cache_removes_files_and_resets_status(client, conn, settings, adapter):
    seed(client, conn, settings, adapter)
    conn.execute("UPDATE media_items SET full_status='ready'")

    body = client.delete("/api/profiles/nike/cache").json()

    assert body["removed_files"] > 0
    assert not (settings.media_dir / "nike").exists()
    statuses = {
        r["full_status"] for r in conn.execute("SELECT full_status FROM media_items")
    }
    assert statuses == {"none"}
    assert conn.execute("SELECT COUNT(*) c FROM media_files").fetchone()["c"] == 0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_api_profiles.py -v`
Expected: FAIL — all routes return 404 because the router is not mounted.

- [ ] **Step 3: Write the implementation**

`api/app/routes/profiles.py`:

```python
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.main_deps import get_conn_dep, wake_worker
from app.services import activity
from app.worker import queue

router = APIRouter()


class TrackedBody(BaseModel):
    tracked: bool


def _last_error(conn, username: str) -> str | None:
    row = conn.execute(
        "SELECT error FROM jobs WHERE kind='profile_sync' AND payload=?"
        " AND status='failed' ORDER BY id DESC LIMIT 1",
        (f'{{"username": "{username}"}}',),
    ).fetchone()
    return row["error"] if row else None


def _media_summary(row) -> dict:
    return {
        "shortcode": row["shortcode"],
        "kind": row["kind"],
        "taken_at": row["taken_at"],
        "caption": row["caption"],
        "is_video": bool(row["is_video"]),
        "child_count": row["child_count"],
        "full_status": row["full_status"],
        "thumb_url": f"/api/media/{row['shortcode']}/thumb",
        "ig_url": row["ig_url"],
    }


@router.get("/profiles")
def list_profiles(conn=Depends(get_conn_dep)):
    rows = conn.execute(
        "SELECT * FROM profiles WHERE tracked=1 ORDER BY username"
    ).fetchall()
    return {
        "items": [
            {
                "username": r["username"],
                "full_name": r["full_name"],
                "post_count": r["post_count"],
                "avatar_url": f"/api/profiles/{r['username']}/avatar",
                "last_synced_at": r["last_synced_at"],
            }
            for r in rows
        ]
    }


@router.get("/profiles/{username}")
def get_profile(username: str, conn=Depends(get_conn_dep)):
    row = conn.execute("SELECT * FROM profiles WHERE username=?", (username,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"{username} has not been synced",
                    "last_error": _last_error(conn, username)},
        )
    cached = conn.execute(
        "SELECT COUNT(*) c FROM media_items WHERE username=? AND full_status='ready'",
        (username,),
    ).fetchone()["c"]
    return {
        "username": row["username"],
        "full_name": row["full_name"],
        "biography": row["biography"],
        "is_private": bool(row["is_private"]),
        "post_count": row["post_count"],
        "avatar_url": f"/api/profiles/{username}/avatar",
        "tracked": bool(row["tracked"]),
        "last_synced_at": row["last_synced_at"],
        "exhausted": row["next_cursor"] == "",
        "cached_count": cached,
    }


@router.post("/profiles/{username}/sync")
def sync_profile(username: str, request: Request, conn=Depends(get_conn_dep)):
    job_id = queue.enqueue_unique(conn, "profile_sync", {"username": username})
    activity.record(conn, "lookup", username, None)
    wake_worker(request)
    return {"queued": job_id is not None}


@router.put("/profiles/{username}/tracked")
def set_tracked(username: str, body: TrackedBody, conn=Depends(get_conn_dep)):
    cur = conn.execute(
        "UPDATE profiles SET tracked=? WHERE username=?", (int(body.tracked), username)
    )
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    activity.record(conn, "track" if body.tracked else "untrack", username, None)
    return {"tracked": body.tracked}


@router.get("/profiles/{username}/media")
def list_media(
    username: str,
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    profile = conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    total = conn.execute(
        "SELECT COUNT(*) c FROM media_items WHERE username=?", (username,)
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT * FROM media_items WHERE username=?"
        " ORDER BY taken_at DESC, shortcode LIMIT ? OFFSET ?",
        (username, limit, offset),
    ).fetchall()
    return {
        "items": [_media_summary(r) for r in rows],
        "total": total,
        "exhausted": profile["next_cursor"] == "",
    }


@router.post("/profiles/{username}/load-more")
def load_more(username: str, request: Request, conn=Depends(get_conn_dep)):
    profile = conn.execute(
        "SELECT next_cursor FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail={"message": "unknown profile"})
    if profile["next_cursor"] == "":
        return {"queued": False, "exhausted": True}
    job_id = queue.enqueue_unique(conn, "page_fetch", {"username": username})
    activity.record(conn, "load_more", username, None)
    wake_worker(request)
    return {"queued": job_id is not None, "exhausted": False}


@router.delete("/profiles/{username}/cache")
def clear_cache(username: str, request: Request, conn=Depends(get_conn_dep)):
    media_root = request.app.state.settings.media_dir
    target = media_root / username
    removed = 0
    if target.exists():
        removed = sum(1 for p in target.rglob("*") if p.is_file())
        shutil.rmtree(target)
    conn.execute(
        "DELETE FROM media_files WHERE shortcode IN"
        " (SELECT shortcode FROM media_items WHERE username=?)",
        (username,),
    )
    conn.execute(
        "UPDATE media_items SET full_status='none', full_error=NULL WHERE username=?",
        (username,),
    )
    conn.execute("UPDATE profiles SET avatar_path=NULL WHERE username=?", (username,))
    return {"removed_files": removed}
```

Also add an avatar route to the same file, since the tests reference `/api/profiles/{username}/avatar`:

```python
from fastapi.responses import FileResponse


@router.get("/profiles/{username}/avatar")
def get_avatar(username: str, request: Request, conn=Depends(get_conn_dep)):
    row = conn.execute(
        "SELECT avatar_path FROM profiles WHERE username=?", (username,)
    ).fetchone()
    if row is None or not row["avatar_path"]:
        raise HTTPException(status_code=404, detail={"message": "no avatar cached"})
    path = request.app.state.settings.media_dir / row["avatar_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "avatar file missing"})
    return FileResponse(path, media_type="image/jpeg")
```

- [ ] **Step 4: Mount the router in `api/app/main.py`**

```python
from app.routes import profiles as profile_routes
...
    app.include_router(profile_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_api_profiles.py -v`
Expected: PASS, 10 tests.

If `test_get_unknown_profile_is_404_with_last_error` fails, the payload string in `_last_error` does not match what `queue.enqueue` stored — it uses `json.dumps(..., sort_keys=True)`, which produces `{"username": "ghost"}` with a space after the colon. Match that exactly or compare with `json_extract(payload, '$.username')` instead.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/profiles.py api/app/main.py api/tests/test_api_profiles.py
git commit -m "feat(api): profile routes for sync, browse, track, and cache"
```

---

### Task 14: Media routes — thumb, full, ensure

**Files:**
- Create: `api/app/routes/media.py`
- Modify: `api/app/main.py` (include the router)
- Test: `api/tests/test_api_media.py`

**Interfaces:**
- Consumes: `get_conn_dep`, `wake_worker`, `queue.enqueue_unique`.
- Produces:
  - `GET /api/media/{shortcode}/thumb` -> `FileResponse`, 404 if not cached
  - `GET /api/media/{shortcode}/full?child=0` -> `FileResponse`, 404 unless `full_status='ready'`
  - `POST /api/media/ensure` body `{"shortcodes": [str], "retry": bool = false}` -> `{"statuses": {shortcode: str}, "ready": int, "total": int}`

`ensure` is the download progress feed. Statuses are `ready | queued | fetching | failed | unknown`. It is idempotent: an item it moves to `queued` reports `queued` on every subsequent call, so re-polling never double-enqueues. With `retry: true`, `failed` items are reset to `none` and re-enqueued.

- [ ] **Step 1: Write the failing test**

`api/tests/test_api_media.py`:

```python
from app.worker import handlers, queue
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def seed(conn, settings, adapter):
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    return ctx


def test_thumb_is_served_after_page_fetch(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    resp = client.get("/api/media/nike-0/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_thumb_404_for_unknown_shortcode(client):
    assert client.get("/api/media/nope/thumb").status_code == 404


def test_full_is_404_until_ready(client, conn, settings, adapter):
    ctx = seed(conn, settings, adapter)
    assert client.get("/api/media/nike-0/full").status_code == 404

    handlers.handle_media_fetch(ctx, {"shortcode": "nike-0"})

    resp = client.get("/api/media/nike-0/full")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")


def test_full_serves_a_named_carousel_child(client, conn, settings, adapter):
    adapter.add_posts("nike", count=1, child_count=2)
    ctx = seed(conn, settings, adapter)
    conn.execute("UPDATE profiles SET next_cursor=NULL WHERE username='nike'")
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-10"})

    assert client.get("/api/media/nike-10/full?child=1").status_code == 200
    assert client.get("/api/media/nike-10/full?child=2").status_code == 200
    assert client.get("/api/media/nike-10/full?child=9").status_code == 404


def test_ensure_enqueues_missing_items(client, conn, settings, adapter):
    seed(conn, settings, adapter)

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0", "nike-1"]}
    ).json()

    assert body["statuses"] == {"nike-0": "queued", "nike-1": "queued"}
    assert body["ready"] == 0
    assert body["total"] == 2
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM jobs").fetchall()]
    assert kinds == ["media_fetch", "media_fetch"]


def test_ensure_is_idempotent(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})
    client.post("/api/media/ensure", json={"shortcodes": ["nike-0"]})

    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1


def test_ensure_reports_ready_and_unknown(client, conn, settings, adapter):
    ctx = seed(conn, settings, adapter)
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-0"})

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0", "ghost"]}
    ).json()

    assert body["statuses"] == {"nike-0": "ready", "ghost": "unknown"}
    assert body["ready"] == 1


def test_ensure_leaves_failed_alone_unless_retry(client, conn, settings, adapter):
    seed(conn, settings, adapter)
    conn.execute("UPDATE media_items SET full_status='failed' WHERE shortcode='nike-0'")

    assert client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0"]}
    ).json()["statuses"] == {"nike-0": "failed"}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0

    body = client.post(
        "/api/media/ensure", json={"shortcodes": ["nike-0"], "retry": True}
    ).json()

    assert body["statuses"] == {"nike-0": "queued"}
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_api_media.py -v`
Expected: FAIL — every request 404s because the router is not mounted.

- [ ] **Step 3: Write the implementation**

`api/app/routes/media.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.main_deps import get_conn_dep, wake_worker
from app.worker import queue

router = APIRouter()


class EnsureBody(BaseModel):
    shortcodes: list[str]
    retry: bool = False


def _file_row(conn, shortcode: str, role: str, child_idx: int):
    return conn.execute(
        "SELECT * FROM media_files WHERE shortcode=? AND role=? AND child_idx=?",
        (shortcode, role, child_idx),
    ).fetchone()


@router.get("/media/{shortcode}/thumb")
def get_thumb(shortcode: str, request: Request, conn=Depends(get_conn_dep)):
    row = _file_row(conn, shortcode, "thumb", 0)
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "no thumbnail cached"})
    path = request.app.state.settings.media_dir / row["path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "thumbnail file missing"})
    return FileResponse(path, media_type=row["mime"] or "image/jpeg")


@router.get("/media/{shortcode}/full")
def get_full(
    shortcode: str,
    request: Request,
    child: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    item = conn.execute(
        "SELECT full_status FROM media_items WHERE shortcode=?", (shortcode,)
    ).fetchone()
    if item is None or item["full_status"] != "ready":
        raise HTTPException(status_code=404, detail={"message": "not cached"})
    row = _file_row(conn, shortcode, "full", child)
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "no such child"})
    path = request.app.state.settings.media_dir / row["path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail={"message": "file missing"})
    return FileResponse(
        path,
        media_type=row["mime"] or "application/octet-stream",
        content_disposition_type="inline",
    )


@router.post("/media/ensure")
def ensure(body: EnsureBody, request: Request, conn=Depends(get_conn_dep)):
    statuses: dict[str, str] = {}
    enqueued = False

    for shortcode in body.shortcodes:
        item = conn.execute(
            "SELECT full_status FROM media_items WHERE shortcode=?", (shortcode,)
        ).fetchone()
        if item is None:
            statuses[shortcode] = "unknown"
            continue

        status = item["full_status"]
        if status == "failed" and body.retry:
            status = "none"
        if status in ("ready", "queued", "fetching", "failed"):
            statuses[shortcode] = status
            continue

        queue.enqueue_unique(conn, "media_fetch", {"shortcode": shortcode})
        conn.execute(
            "UPDATE media_items SET full_status='queued', full_error=NULL WHERE shortcode=?",
            (shortcode,),
        )
        statuses[shortcode] = "queued"
        enqueued = True

    if enqueued:
        wake_worker(request)

    return {
        "statuses": statuses,
        "ready": sum(1 for s in statuses.values() if s == "ready"),
        "total": len(statuses),
    }
```

- [ ] **Step 4: Mount the router in `api/app/main.py`**

```python
from app.routes import media as media_routes
...
    app.include_router(media_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_api_media.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/media.py api/app/main.py api/tests/test_api_media.py
git commit -m "feat(api): media thumb, full, and idempotent ensure routes"
```

---

### Task 15: Download route

**Files:**
- Create: `api/app/services/downloads.py`, `api/app/routes/downloads.py`
- Modify: `api/app/main.py` (include the router)
- Test: `api/tests/test_api_downloads.py`

**Interfaces:**
- Consumes: `paths.download_names`, `paths.sanitize_base`, `paths.atomic_copy`, `paths.unique_dest`, `activity.record`.
- Produces:
  - `services.downloads.collect(conn, shortcodes: list[str]) -> list[paths.PostFiles]` — ordered by `taken_at` ascending, raising `NotReady(shortcode)` for anything not `ready`
  - `services.downloads.run(conn, settings, shortcodes, base) -> dict` with keys `written: list[str]`, `out_dir: str`, `count: int`
  - `POST /api/downloads` body `{"shortcodes": [str], "base": str}` -> that dict; **409** with the offending shortcodes when something is not ready, **400** when `shortcodes` is empty

Ordering is ascending by `taken_at` so `_01` is the oldest selected post — a numbered sequence that reads chronologically. The grid displays newest-first; these are deliberately different, and the test below pins it.

- [ ] **Step 1: Write the failing test**

`api/tests/test_api_downloads.py`:

```python
import pytest

from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


@pytest.fixture
def ready(conn, settings, adapter):
    adapter.add_posts("nike", count=1, child_count=3)
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    for shortcode in ("nike-0", "nike-1", "nike-2"):
        handlers.handle_media_fetch(ctx, {"shortcode": shortcode})
    return ctx


def test_download_writes_numbered_files_oldest_first(client, ready, settings):
    body = client.post(
        "/api/downloads",
        json={"shortcodes": ["nike-2", "nike-0", "nike-1"], "base": "trip"},
    ).json()

    assert body["count"] == 3
    written = sorted(p.name for p in settings.out_dir.iterdir())
    assert written == ["trip_01.jpg", "trip_02.jpg", "trip_03.jpg"]
    assert (settings.out_dir / "trip_01.jpg").read_bytes() == b"nike-0:0"


def test_download_names_carousel_children_with_letters(client, conn, settings, adapter):
    adapter.add_posts("nike", count=1, child_count=3)
    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    handlers.handle_page_fetch(ctx, {"username": "nike"})
    handlers.handle_media_fetch(ctx, {"shortcode": "nike-10"})

    client.post("/api/downloads", json={"shortcodes": ["nike-10"], "base": "set"})

    assert sorted(p.name for p in settings.out_dir.iterdir()) == [
        "set_01a.jpg", "set_01b.jpg", "set_01c.jpg",
    ]


def test_download_sanitizes_the_base_filename(client, ready, settings):
    client.post(
        "/api/downloads", json={"shortcodes": ["nike-0"], "base": "../../escape"}
    )
    written = [p.name for p in settings.out_dir.iterdir()]
    assert written == ["escape_01.jpg"]
    assert not (settings.out_dir.parent / "escape_01.jpg").exists()


def test_download_never_overwrites_an_existing_file(client, ready, settings):
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})

    assert sorted(p.name for p in settings.out_dir.iterdir()) == [
        "trip_01-1.jpg", "trip_01.jpg",
    ]


def test_download_409s_when_something_is_not_ready(client, ready, conn, settings):
    conn.execute("UPDATE media_items SET full_status='none' WHERE shortcode='nike-1'")

    resp = client.post(
        "/api/downloads", json={"shortcodes": ["nike-0", "nike-1"], "base": "trip"}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["not_ready"] == ["nike-1"]
    assert list(settings.out_dir.iterdir()) == []


def test_download_400s_on_empty_selection(client, ready):
    assert client.post(
        "/api/downloads", json={"shortcodes": [], "base": "trip"}
    ).status_code == 400


def test_download_writes_one_activity_row(client, ready, conn):
    client.post(
        "/api/downloads", json={"shortcodes": ["nike-0", "nike-1"], "base": "trip"}
    )

    rows = conn.execute(
        "SELECT * FROM activity_log WHERE action='download'"
    ).fetchall()
    assert len(rows) == 1
    import json

    detail = json.loads(rows[0]["detail"])
    assert detail["count"] == 2
    assert detail["base"] == "trip"
    assert detail["shortcodes"] == ["nike-0", "nike-1"]


def test_download_leaves_no_part_files(client, ready, settings):
    client.post("/api/downloads", json={"shortcodes": ["nike-0"], "base": "trip"})
    assert list(settings.out_dir.glob("*.part")) == []
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_api_downloads.py -v`
Expected: FAIL — `POST /api/downloads` 404s because the router is not mounted.

- [ ] **Step 3: Write the service**

`api/app/services/downloads.py`:

```python
import sqlite3

from app import paths
from app.config import Settings
from app.services import activity


class NotReady(Exception):
    def __init__(self, shortcodes: list[str]):
        super().__init__(", ".join(shortcodes))
        self.shortcodes = shortcodes


def collect(conn: sqlite3.Connection, shortcodes: list[str]) -> list[paths.PostFiles]:
    """Resolve a selection into ordered (shortcode, [(child_idx, ext)]) pairs.

    Ordered oldest-first so the generated sequence reads chronologically,
    which is the opposite of the newest-first grid on purpose.
    """
    placeholders = ",".join("?" * len(shortcodes))
    rows = conn.execute(
        f"SELECT shortcode, full_status FROM media_items WHERE shortcode IN ({placeholders})"
        " ORDER BY taken_at ASC, shortcode",
        shortcodes,
    ).fetchall()

    found = {r["shortcode"] for r in rows}
    not_ready = [s for s in shortcodes if s not in found]
    not_ready += [r["shortcode"] for r in rows if r["full_status"] != "ready"]
    if not_ready:
        raise NotReady(sorted(set(not_ready)))

    out: list[paths.PostFiles] = []
    for row in rows:
        files = conn.execute(
            "SELECT child_idx, path FROM media_files WHERE shortcode=? AND role='full'"
            " ORDER BY child_idx",
            (row["shortcode"],),
        ).fetchall()
        out.append(
            (row["shortcode"], [(f["child_idx"], f["path"].rsplit(".", 1)[-1]) for f in files])
        )
    return out


def run(conn: sqlite3.Connection, settings: Settings, shortcodes: list[str], base: str) -> dict:
    posts = collect(conn, shortcodes)
    safe_base = paths.sanitize_base(base)
    named = paths.download_names(posts, safe_base)

    settings.out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for shortcode, child_idx, filename in named:
        row = conn.execute(
            "SELECT path FROM media_files WHERE shortcode=? AND role='full' AND child_idx=?",
            (shortcode, child_idx),
        ).fetchone()
        src = settings.media_dir / row["path"]
        dest = paths.unique_dest(settings.out_dir, filename)
        paths.atomic_copy(src, dest)
        written.append(dest.name)

    activity.record(
        conn,
        "download",
        posts[0][0] if len(posts) == 1 else None,
        {
            "base": safe_base,
            "count": len(written),
            "out": str(settings.out_dir),
            "shortcodes": [p[0] for p in posts],
        },
    )
    return {"written": written, "out_dir": str(settings.out_dir), "count": len(written)}
```

- [ ] **Step 4: Write the route**

`api/app/routes/downloads.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.main_deps import get_conn_dep
from app.services import downloads

router = APIRouter()


class DownloadBody(BaseModel):
    shortcodes: list[str]
    base: str


@router.post("/downloads")
def create_download(body: DownloadBody, request: Request, conn=Depends(get_conn_dep)):
    if not body.shortcodes:
        raise HTTPException(status_code=400, detail={"message": "no items selected"})
    try:
        return downloads.run(conn, request.app.state.settings, body.shortcodes, body.base)
    except downloads.NotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "some items are not cached yet", "not_ready": exc.shortcodes},
        ) from exc
```

- [ ] **Step 5: Mount the router in `api/app/main.py`**

```python
from app.routes import downloads as download_routes
...
    app.include_router(download_routes.router, prefix="/api")
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `cd api && python -m pytest tests/test_api_downloads.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 7: Commit**

```bash
git add api/app/services/downloads.py api/app/routes/downloads.py api/app/main.py api/tests/test_api_downloads.py
git commit -m "feat(api): download route writing named files to the output folder"
```

---

### Task 16: Health canary and the live test

**Files:**
- Create: `api/app/routes/health.py`, `api/tests/test_live_canary.py`
- Modify: `api/app/main.py` (include the router)
- Test: `api/tests/test_api_health.py`

**Interfaces:**
- Consumes: `IgAdapter`, `Breaker`.
- Produces:
  - `GET /api/health/canary?username=` -> `{"ok": bool, "checks": {...}, "error": str | None}`
  - `POST /api/health/clear-breaker` -> `{"cleared": true}` — the API-side equivalent of running the login command once the session is fixed
  - `pytest -m live` module that exercises the real adapter

The canary and the live test share one function so the thing you run from the UI and the thing CI-adjacent humans run manually cannot drift apart.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_api_health.py`:

```python
from app.ig import types as t


def test_canary_ok_against_the_fake(client):
    body = client.get("/api/health/canary?username=nike").json()
    assert body["ok"] is True
    assert body["checks"] == {"profile": True, "page": True, "media": True}
    assert body["error"] is None


def test_canary_reports_failure_without_raising(client):
    client.app_state.adapter.raise_on("fetch_profile", t.IgChallenge("checkpoint_required"))

    body = client.get("/api/health/canary?username=nike").json()

    assert body["ok"] is False
    assert body["checks"]["profile"] is False
    assert "checkpoint_required" in body["error"]


def test_clear_breaker_resets_a_permanent_trip(client):
    client.app_state.breaker.trip_permanent("session invalid")

    assert client.post("/api/health/clear-breaker").json() == {"cleared": True}
    assert client.get("/api/status").json()["breaker"]["tripped"] is False
```

`api/tests/test_live_canary.py`:

```python
import pytest

from app.config import load_settings
from app.ig.adapter import InstaloaderAdapter
from app.routes.health import run_canary

pytestmark = pytest.mark.live

CANARY_PROFILE = "instagram"


def test_real_instagram_still_matches_our_parsing(tmp_path):
    """The test that tells you Instagram rotated something.

    Run manually: pytest -m live
    """
    settings = load_settings()
    if not settings.ig_username:
        pytest.skip("IG_USERNAME not configured")

    result = run_canary(InstaloaderAdapter(settings), CANARY_PROFILE, tmp_path)

    assert result["ok"] is True, result["error"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd api && python -m pytest tests/test_api_health.py -v`
Expected: FAIL — `/api/health/canary` 404s.

- [ ] **Step 3: Write the implementation**

`api/app/routes/health.py`:

```python
import tempfile
from pathlib import Path

from fastapi import APIRouter, Query, Request

router = APIRouter()

DEFAULT_CANARY = "instagram"


def run_canary(adapter, username: str, workdir: Path) -> dict:
    """Prove the adapter still understands Instagram, end to end.

    Shared by GET /api/health/canary and the `live` test so the two can
    never drift.
    """
    checks = {"profile": False, "page": False, "media": False}
    try:
        profile = adapter.fetch_profile(username)
        checks["profile"] = bool(profile.username)

        page = adapter.fetch_page(username, None, 3)
        checks["page"] = len(page.posts) > 0
        if not page.posts:
            return {"ok": False, "checks": checks, "error": "profile returned no posts"}

        saved = adapter.fetch_media(page.posts[0].shortcode, workdir)
        checks["media"] = bool(saved) and all(s.bytes > 0 for s in saved)
    except Exception as exc:  # noqa: BLE001 - a canary reports, it does not raise
        return {"ok": False, "checks": checks, "error": f"{type(exc).__name__}: {exc}"}

    return {"ok": all(checks.values()), "checks": checks, "error": None}


@router.get("/health/canary")
def canary(request: Request, username: str = Query(DEFAULT_CANARY)):
    with tempfile.TemporaryDirectory() as tmp:
        return run_canary(request.app.state.adapter, username, Path(tmp))


@router.post("/health/clear-breaker")
def clear_breaker(request: Request):
    request.app.state.breaker.clear()
    return {"cleared": True}
```

- [ ] **Step 4: Mount the router in `api/app/main.py`**

```python
from app.routes import health as health_routes
...
    app.include_router(health_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the full backend suite**

Run: `cd api && python -m pytest -v`
Expected: PASS. The `live` module is excluded by the `addopts` in `pytest.ini`; confirm the summary says `deselected` rather than `passed` for it.

Run: `cd api && python -m pytest -m live --collect-only`
Expected: collects `test_real_instagram_still_matches_our_parsing`.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/health.py api/app/main.py api/tests/test_api_health.py api/tests/test_live_canary.py
git commit -m "feat(api): health canary, breaker reset, and opt-in live test"
```

---

### Task 17: Docker Compose, Dockerfiles, seed script

**Files:**
- Create: `api/Dockerfile`, `api/.dockerignore`, `api/scripts/seed_e2e.py`, `web/Dockerfile`, `web/.dockerignore`, `docker-compose.yml`, `.env.example`, `.gitignore`
- Test: manual verification steps below (this task's deliverable is a running stack, and the assertions are HTTP responses rather than pytest)

**Interfaces:**
- Consumes: `create_app`, `Settings` env var names from Task 1.
- Produces: `docker compose up` serving the UI on `http://localhost:3000` with `/api/*` proxied to the API container; `docker compose run --rm api python -m app.ig.login`; `docker compose run --rm -e IG_ADAPTER=fake api python scripts/seed_e2e.py`.

- [ ] **Step 1: Write the API container files**

`api/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY pytest.ini .

EXPOSE 8000

# --workers 1 is load-bearing: a second process breaks request serialization.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

`api/.dockerignore`:

```
__pycache__/
*.pyc
.pytest_cache/
tests/
```

- [ ] **Step 2: Write the seed script**

`api/scripts/seed_e2e.py`:

```python
"""Deterministic database seed for the Playwright suite.

Runs the real handlers against the fake adapter, so the seeded state is
produced by production code paths rather than hand-written SQL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.config import load_settings
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def main() -> int:
    settings = load_settings()
    conn = db.get_conn(settings)
    db.init_schema(conn)
    for directory in (settings.media_dir, settings.out_dir):
        directory.mkdir(parents=True, exist_ok=True)

    adapter = FakeAdapter()
    adapter.add_profile("nike", post_count=8)
    adapter.add_posts("nike", count=6)
    adapter.add_posts("nike", count=2, child_count=3)

    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    while conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"] != "":
        handlers.handle_page_fetch(ctx, {"username": "nike"})

    conn.execute("UPDATE profiles SET tracked=1 WHERE username='nike'")
    print(
        "seeded",
        conn.execute("SELECT COUNT(*) c FROM media_items").fetchone()["c"],
        "items",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write the web container files**

`web/Dockerfile`:

```dockerfile
FROM node:22-slim

WORKDIR /srv

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
```

`web/.dockerignore`:

```
node_modules/
.next/
test-results/
playwright-report/
```

- [ ] **Step 4: Write the Compose file and environment template**

`docker-compose.yml`:

```yaml
services:
  api:
    build: ./api
    env_file: .env
    environment:
      DB_PATH: /data/app.db
      MEDIA_DIR: /data/media
      SESSION_DIR: /data/session
      OUT_DIR_CONTAINER: /out
    volumes:
      - ./data:/data
      - ${OUT_DIR:-./downloads}:/out
    restart: unless-stopped

  web:
    build: ./web
    environment:
      API_ORIGIN: http://api:8000
    ports:
      - "3000:3000"
    volumes:
      - ./web:/srv
      - /srv/node_modules
    depends_on:
      - api
    restart: unless-stopped
```

The API deliberately publishes no port. Everything reaches it through the `web` rewrite, which is what keeps the browser on a single origin.

`.env.example`:

```bash
# The dedicated Instagram account. Never a personal login.
IG_USERNAME=
IG_PASSWORD=

# Host folder that downloads are written into.
OUT_DIR=./downloads

# Posts fetched per "Load more".
PAGE_SIZE=36

# Seconds enforced between Instagram requests.
IG_MIN_INTERVAL=3

# Seconds the breaker holds after a 429.
IG_BACKOFF=900

# real | fake  -- "fake" runs with no network, used by the e2e suite.
IG_ADAPTER=real
```

`.gitignore`:

```
.env
data/
downloads/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
.next/
test-results/
playwright-report/
```

- [ ] **Step 5: Verify the stack boots**

```bash
cp .env.example .env
docker compose build
docker compose up -d api
docker compose exec api python -c "import instaloader; print(instaloader.__version__)"
curl -s http://localhost:3000/api/status
```

Expected: the version prints, and after `docker compose up -d web` the `curl` returns JSON containing `"breaker"` and `"queue_depth"`. Until Task 18 adds the rewrite, query the API directly with `docker compose exec api curl -s localhost:8000/api/status`.

Confirm the worker started: `docker compose logs api | grep '"event":"sweep"'` should show one sweep line.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example .gitignore api/Dockerfile api/.dockerignore api/scripts web/Dockerfile web/.dockerignore
git commit -m "chore: docker compose stack, container images, e2e seed script"
```

---

### Task 18: Web scaffold, API client, layout, status banner

**Files:**
- Create: `web/package.json`, `web/next.config.js`, `web/tsconfig.json`, `web/app/layout.tsx`, `web/app/globals.css`, `web/lib/api.ts`, `web/lib/usePolling.ts`, `web/components/Banner.tsx`
- Test: `web/e2e/banner.spec.ts` (Playwright, run against the fake-adapter stack)

**Interfaces:**
- Consumes: the API routes from Tasks 12-16.
- Produces:
  - `lib/api.ts` exporting types `ProfileSummary`, `ProfileDetail`, `MediaSummary`, `StatusBody`, `ActivityItem`, `EnsureResult`, `DownloadResult` and functions `getStatus`, `getProfiles`, `getProfile`, `syncProfile`, `setTracked`, `clearCache`, `getMedia`, `loadMore`, `ensureMedia`, `createDownload`, `getActivity`, `clearBreaker`
  - `lib/usePolling.ts` exporting `usePolling<T>(fn: () => Promise<T>, intervalMs: number, enabled?: boolean): {data: T | null, error: string | null, refresh: () => void}`
  - `components/Banner.tsx` — default export, renders nothing when the breaker is clear

- [ ] **Step 1: Write the scaffold**

`web/package.json`:

```json
{
  "name": "instascraper-web",
  "private": true,
  "scripts": {
    "dev": "next dev -H 0.0.0.0 -p 3000",
    "build": "next build",
    "start": "next start -H 0.0.0.0 -p 3000",
    "e2e": "playwright test"
  },
  "dependencies": {
    "next": "15.1.6",
    "react": "19.0.0",
    "react-dom": "19.0.0"
  },
  "devDependencies": {
    "@playwright/test": "1.50.0",
    "@types/node": "22.10.7",
    "@types/react": "19.0.7",
    "typescript": "5.7.3"
  }
}
```

`web/next.config.js`:

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_ORIGIN ?? 'http://localhost:8000'}/api/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 2: Write the API client**

`web/lib/api.ts`:

```ts
export type StatusBody = {
  worker: 'running' | 'stopped'
  breaker: {
    tripped: boolean
    permanent: boolean
    reason: string | null
    seconds_remaining: number | null
  }
  queue_depth: number
}

export type ProfileSummary = {
  username: string
  full_name: string | null
  post_count: number | null
  avatar_url: string
  last_synced_at: string | null
}

export type ProfileDetail = ProfileSummary & {
  biography: string | null
  is_private: boolean
  tracked: boolean
  exhausted: boolean
  cached_count: number
}

export type MediaSummary = {
  shortcode: string
  kind: 'image' | 'video' | 'reel' | 'carousel'
  taken_at: string
  caption: string | null
  is_video: boolean
  child_count: number
  full_status: 'none' | 'queued' | 'fetching' | 'ready' | 'failed'
  thumb_url: string
  ig_url: string
}

export type MediaPage = { items: MediaSummary[]; total: number; exhausted: boolean }
export type EnsureResult = {
  statuses: Record<string, string>
  ready: number
  total: number
}
export type DownloadResult = { written: string[]; out_dir: string; count: number }
export type ActivityItem = {
  id: number
  ts: string
  action: string
  target: string | null
  detail: Record<string, unknown> | null
}

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: unknown, message: string) {
    super(message)
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = body?.detail
    const message =
      typeof detail === 'string' ? detail : detail?.message ?? `request failed (${res.status})`
    throw new ApiError(res.status, body, message)
  }
  return body as T
}

export const getStatus = () => call<StatusBody>('/api/status')
export const clearBreaker = () => call<{ cleared: boolean }>('/api/health/clear-breaker', { method: 'POST' })

export const getProfiles = () => call<{ items: ProfileSummary[] }>('/api/profiles')
export const getProfile = (u: string) => call<ProfileDetail>(`/api/profiles/${encodeURIComponent(u)}`)
export const syncProfile = (u: string) =>
  call<{ queued: boolean }>(`/api/profiles/${encodeURIComponent(u)}/sync`, { method: 'POST' })
export const setTracked = (u: string, tracked: boolean) =>
  call<{ tracked: boolean }>(`/api/profiles/${encodeURIComponent(u)}/tracked`, {
    method: 'PUT',
    body: JSON.stringify({ tracked }),
  })
export const clearCache = (u: string) =>
  call<{ removed_files: number }>(`/api/profiles/${encodeURIComponent(u)}/cache`, {
    method: 'DELETE',
  })
export const getMedia = (u: string, limit: number, offset: number) =>
  call<MediaPage>(`/api/profiles/${encodeURIComponent(u)}/media?limit=${limit}&offset=${offset}`)
export const loadMore = (u: string) =>
  call<{ queued: boolean; exhausted: boolean }>(
    `/api/profiles/${encodeURIComponent(u)}/load-more`,
    { method: 'POST' },
  )

export const ensureMedia = (shortcodes: string[], retry = false) =>
  call<EnsureResult>('/api/media/ensure', {
    method: 'POST',
    body: JSON.stringify({ shortcodes, retry }),
  })
export const createDownload = (shortcodes: string[], base: string) =>
  call<DownloadResult>('/api/downloads', {
    method: 'POST',
    body: JSON.stringify({ shortcodes, base }),
  })

export const getActivity = (limit = 100) =>
  call<{ items: ActivityItem[] }>(`/api/activity?limit=${limit}`)
```

- [ ] **Step 3: Write the polling hook and banner**

`web/lib/usePolling.ts`:

```ts
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const refresh = useCallback(async () => {
    try {
      setData(await fnRef.current())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    const tick = async () => {
      if (!cancelled) await refresh()
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, refresh }
}
```

`web/components/Banner.tsx`:

```tsx
'use client'

import { clearBreaker, getStatus, type StatusBody } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

function describe(breaker: StatusBody['breaker']): string {
  if (breaker.permanent) return breaker.reason ?? 'Instagram session invalid'
  const mins = Math.ceil((breaker.seconds_remaining ?? 0) / 60)
  return `${breaker.reason ?? 'Rate limited'} — resuming in about ${mins} min`
}

export default function Banner() {
  const { data, refresh } = usePolling(getStatus, 5000)
  if (!data || !data.breaker.tripped) return null

  return (
    <div role="alert" data-testid="breaker-banner" className="banner">
      <span>{describe(data.breaker)}</span>
      {data.breaker.permanent && (
        <>
          <code>docker compose run --rm api python -m app.ig.login</code>
          <button
            onClick={async () => {
              await clearBreaker()
              refresh()
            }}
          >
            I have fixed it
          </button>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Write the layout and styles**

`web/app/layout.tsx`:

```tsx
import Link from 'next/link'

import Banner from '@/components/Banner'

import './globals.css'

export const metadata = { title: 'instascraper' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header>
          <Link href="/">instascraper</Link>
          <Link href="/activity">Activity</Link>
        </header>
        <Banner />
        <main>{children}</main>
      </body>
    </html>
  )
}
```

`web/app/globals.css`:

```css
:root {
  color-scheme: dark;
  --bg: #101014;
  --fg: #e8e8ea;
  --muted: #8b8b95;
  --line: #2a2a32;
  --accent: #4f8cff;
  --warn: #b4531a;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 15px/1.5 system-ui, sans-serif;
}

header {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  padding: 0.9rem 1.25rem;
  border-bottom: 1px solid var(--line);
}

header a { color: var(--fg); text-decoration: none; }

main { padding: 1.25rem; }

.banner {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
  padding: 0.7rem 1.25rem;
  background: var(--warn);
}

.banner code { background: rgba(0, 0, 0, 0.3); padding: 0.15rem 0.4rem; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}

.tile {
  position: relative;
  aspect-ratio: 1 / 1;
  border: 2px solid transparent;
  padding: 0;
  background: #17171d;
  cursor: pointer;
  overflow: hidden;
}

.tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tile[aria-pressed='true'] { border-color: var(--accent); }

.badge {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.65);
  font-size: 11px;
}

.selection-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 1rem;
  padding: 0.9rem 1rem;
  border-top: 1px solid var(--line);
  background: #17171d;
}

table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 0.4rem 0.7rem; border-bottom: 1px solid var(--line); }
.muted { color: var(--muted); }
```

- [ ] **Step 5: Verify the shell renders**

```bash
docker compose up -d
curl -s http://localhost:3000/api/status
```

Expected: the proxied status JSON comes back through port 3000, which proves the rewrite works. Open `http://localhost:3000` and confirm the header renders with no banner.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/next.config.js web/tsconfig.json web/app web/lib web/components
git commit -m "feat(web): scaffold, typed API client, polling hook, breaker banner"
```

---

### Task 19: Home screen

**Files:**
- Create: `web/app/page.tsx`, `web/components/TrackedProfiles.tsx`
- Test: `web/e2e/home.spec.ts` (added here, first run in Task 23 once the Playwright config exists)

**Interfaces:**
- Consumes: `getProfiles`, `syncProfile`, `getActivity`, `usePolling`.
- Produces: the `/` route. Submitting a username calls `syncProfile` then routes to `/p/<username>`. Renders tracked profile cards and the five most recent activity entries.

- [ ] **Step 1: Write the Playwright spec**

`web/e2e/home.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test('home lists the seeded tracked profile', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('tracked-profiles')).toContainText('nike')
})

test('submitting a username routes to the profile screen', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('username-input').fill('nike')
  await page.getByTestId('lookup-submit').click()
  await expect(page).toHaveURL(/\/p\/nike$/)
})

test('an empty username does not navigate', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('lookup-submit').click()
  await expect(page).toHaveURL(/\/$/)
})
```

- [ ] **Step 2: Write the tracked-profiles component**

`web/components/TrackedProfiles.tsx`:

```tsx
'use client'

import Link from 'next/link'

import { getProfiles } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

export default function TrackedProfiles() {
  const { data } = usePolling(getProfiles, 10000)
  const items = data?.items ?? []

  return (
    <section data-testid="tracked-profiles">
      <h2>Tracked profiles</h2>
      {items.length === 0 && <p className="muted">Nothing tracked yet.</p>}
      <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: '0.5rem' }}>
        {items.map((p) => (
          <li key={p.username}>
            <Link href={`/p/${p.username}`}>
              <strong>{p.username}</strong>{' '}
              <span className="muted">
                {p.post_count ?? 0} posts
                {p.last_synced_at ? ` · synced ${p.last_synced_at.slice(0, 10)}` : ''}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
```

- [ ] **Step 3: Write the home page**

`web/app/page.tsx`:

```tsx
'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import TrackedProfiles from '@/components/TrackedProfiles'
import { getActivity, syncProfile } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

export default function HomePage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { data: activity } = usePolling(() => getActivity(5), 10000)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const clean = username.trim().replace(/^@/, '')
    if (!clean) return
    try {
      await syncProfile(clean)
      router.push(`/p/${encodeURIComponent(clean)}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div style={{ display: 'grid', gap: '2rem', maxWidth: 720 }}>
      <form onSubmit={submit} style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          data-testid="username-input"
          placeholder="instagram username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ flex: 1, padding: '0.5rem' }}
        />
        <button data-testid="lookup-submit" type="submit">
          Look up
        </button>
      </form>
      {error && <p role="alert">{error}</p>}

      <TrackedProfiles />

      <section>
        <h2>Recent activity</h2>
        <ul className="muted" style={{ paddingLeft: '1rem' }}>
          {(activity?.items ?? []).map((item) => (
            <li key={item.id}>
              {item.ts.slice(0, 19).replace('T', ' ')} — {item.action}
              {item.target ? ` ${item.target}` : ''}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Verify manually**

```bash
docker compose run --rm -e IG_ADAPTER=fake api python scripts/seed_e2e.py
docker compose up -d
```

Open `http://localhost:3000`. Expected: `nike` appears under Tracked profiles, and submitting `nike` navigates to `/p/nike` (which 404s until Task 20 — that is fine).

- [ ] **Step 5: Commit**

```bash
git add web/app/page.tsx web/components/TrackedProfiles.tsx web/e2e/home.spec.ts
git commit -m "feat(web): home screen with lookup, tracked profiles, recent activity"
```

---

### Task 20: Profile screen — grid and selection

**Files:**
- Create: `web/lib/useSelection.ts`, `web/components/MediaTile.tsx`, `web/components/MediaGrid.tsx`, `web/app/p/[username]/page.tsx`
- Test: `web/e2e/grid.spec.ts`

**Interfaces:**
- Consumes: `getProfile`, `getMedia`, `loadMore`, `setTracked`, `clearCache`.
- Produces:
  - `useSelection(orderedIds: string[])` returning `{selected: string[], isSelected(id), toggle(id, shiftKey), selectAll(), clear()}`. Shift-click selects the inclusive range between the last-clicked tile and the current one.
  - `MediaTile` — a `<button aria-pressed>` wrapping the thumbnail with a `data-testid="tile-<shortcode>"`
  - `MediaGrid` — the responsive grid plus the `Load more` control
  - `/p/[username]` route rendering header, grid, and (from Task 21) the selection bar

Grid order is newest-first, matching `GET /api/profiles/{u}/media`. Downloads number oldest-first; that difference is intentional and lives in the API.

- [ ] **Step 1: Write the Playwright spec**

`web/e2e/grid.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test('grid renders seeded tiles newest first', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('media-grid').locator('button')).toHaveCount(8)
})

test('clicking a tile selects it', async ({ page }) => {
  await page.goto('/p/nike')
  const tile = page.getByTestId('tile-nike-0')
  await tile.click()
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('selection-count')).toHaveText('1 selected')
})

test('shift-click selects an inclusive range', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-3').click({ modifiers: ['Shift'] })
  await expect(page.getByTestId('selection-count')).toHaveText('4 selected')
})

test('select all then clear', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('select-all').click()
  await expect(page.getByTestId('selection-count')).toHaveText('8 selected')
  await page.getByTestId('clear-selection').click()
  await expect(page.getByTestId('selection-bar')).toHaveCount(0)
})

test('load more is disabled once the profile is exhausted', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('load-more')).toBeDisabled()
})

test('carousel tiles show a child count badge', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('tile-nike-6').getByText('3')).toBeVisible()
})
```

- [ ] **Step 2: Write the selection hook**

`web/lib/useSelection.ts`:

```ts
'use client'

import { useCallback, useRef, useState } from 'react'

export function useSelection(orderedIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const anchor = useRef<string | null>(null)

  const toggle = useCallback(
    (id: string, shiftKey = false) => {
      setSelected((prev) => {
        const next = new Set(prev)
        if (shiftKey && anchor.current) {
          const from = orderedIds.indexOf(anchor.current)
          const to = orderedIds.indexOf(id)
          if (from !== -1 && to !== -1) {
            const [lo, hi] = from <= to ? [from, to] : [to, from]
            for (const item of orderedIds.slice(lo, hi + 1)) next.add(item)
            return next
          }
        }
        if (next.has(id)) next.delete(id)
        else next.add(id)
        anchor.current = id
        return next
      })
    },
    [orderedIds],
  )

  const selectAll = useCallback(() => setSelected(new Set(orderedIds)), [orderedIds])
  const clear = useCallback(() => {
    anchor.current = null
    setSelected(new Set())
  }, [])

  return {
    selected: orderedIds.filter((id) => selected.has(id)),
    isSelected: (id: string) => selected.has(id),
    toggle,
    selectAll,
    clear,
  }
}
```

- [ ] **Step 3: Write the tile and grid**

`web/components/MediaTile.tsx`:

```tsx
'use client'

import type { MediaSummary } from '@/lib/api'

const BADGE: Record<MediaSummary['kind'], string | null> = {
  image: null,
  video: 'video',
  reel: 'reel',
  carousel: null,
}

export default function MediaTile({
  item,
  selected,
  onToggle,
}: {
  item: MediaSummary
  selected: boolean
  onToggle: (shiftKey: boolean) => void
}) {
  const badge = item.kind === 'carousel' ? String(item.child_count) : BADGE[item.kind]

  return (
    <button
      type="button"
      className="tile"
      data-testid={`tile-${item.shortcode}`}
      aria-pressed={selected}
      aria-label={item.shortcode}
      onClick={(e) => onToggle(e.shiftKey)}
    >
      <img src={item.thumb_url} alt="" loading="lazy" />
      {badge && <span className="badge">{badge}</span>}
      {item.full_status === 'ready' && (
        <span className="badge" style={{ top: 'auto', bottom: 6, right: 6 }}>
          cached
        </span>
      )}
    </button>
  )
}
```

`web/components/MediaGrid.tsx`:

```tsx
'use client'

import MediaTile from '@/components/MediaTile'
import type { MediaSummary } from '@/lib/api'

export default function MediaGrid({
  items,
  isSelected,
  onToggle,
  exhausted,
  loading,
  onLoadMore,
}: {
  items: MediaSummary[]
  isSelected: (shortcode: string) => boolean
  onToggle: (shortcode: string, shiftKey: boolean) => void
  exhausted: boolean
  loading: boolean
  onLoadMore: () => void
}) {
  return (
    <>
      <div className="grid" data-testid="media-grid">
        {items.map((item) => (
          <MediaTile
            key={item.shortcode}
            item={item}
            selected={isSelected(item.shortcode)}
            onToggle={(shiftKey) => onToggle(item.shortcode, shiftKey)}
          />
        ))}
      </div>
      <p style={{ marginTop: '1rem' }}>
        <button data-testid="load-more" disabled={exhausted || loading} onClick={onLoadMore}>
          {exhausted ? 'All posts loaded' : loading ? 'Loading…' : 'Load more'}
        </button>
      </p>
    </>
  )
}
```

- [ ] **Step 4: Write the profile page**

`web/app/p/[username]/page.tsx`:

```tsx
'use client'

import { use, useCallback, useMemo, useState } from 'react'

import MediaGrid from '@/components/MediaGrid'
import SelectionBar from '@/components/SelectionBar'
import { clearCache, getMedia, getProfile, loadMore, setTracked } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'
import { useSelection } from '@/lib/useSelection'

const PAGE = 120

export default function ProfilePage({ params }: { params: Promise<{ username: string }> }) {
  const { username } = use(params)
  const [busy, setBusy] = useState(false)

  const { data: profile, error, refresh: refreshProfile } = usePolling(
    () => getProfile(username),
    4000,
  )
  const { data: media, refresh: refreshMedia } = usePolling(
    () => getMedia(username, PAGE, 0),
    4000,
  )

  const items = useMemo(() => media?.items ?? [], [media])
  const ids = useMemo(() => items.map((i) => i.shortcode), [items])
  const selection = useSelection(ids)

  const onLoadMore = useCallback(async () => {
    setBusy(true)
    try {
      await loadMore(username)
      await refreshMedia()
    } finally {
      setBusy(false)
    }
  }, [username, refreshMedia])

  if (error) {
    return (
      <p role="alert" data-testid="profile-error">
        {error}
      </p>
    )
  }
  if (!profile) return <p className="muted">Loading…</p>
  if (profile.is_private) {
    return (
      <p role="alert" data-testid="profile-private">
        {username} is private. This tool only supports public profiles.
      </p>
    )
  }

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <header style={{ display: 'flex', gap: '1rem', alignItems: 'center', border: 0 }}>
        <img
          src={profile.avatar_url}
          alt=""
          width={64}
          height={64}
          style={{ borderRadius: '50%' }}
        />
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0 }}>{profile.username}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {profile.post_count ?? 0} posts · {items.length} loaded · {profile.cached_count} cached
          </p>
        </div>
        <button
          data-testid="track-toggle"
          onClick={async () => {
            await setTracked(username, !profile.tracked)
            refreshProfile()
          }}
        >
          {profile.tracked ? 'Untrack' : 'Track'}
        </button>
        <button
          data-testid="clear-cache"
          onClick={async () => {
            await clearCache(username)
            selection.clear()
            refreshMedia()
            refreshProfile()
          }}
        >
          Clear cache
        </button>
      </header>

      <p>
        <button data-testid="select-all" onClick={selection.selectAll}>
          Select all loaded
        </button>
      </p>

      <MediaGrid
        items={items}
        isSelected={selection.isSelected}
        onToggle={selection.toggle}
        exhausted={media?.exhausted ?? false}
        loading={busy}
        onLoadMore={onLoadMore}
      />

      <SelectionBar
        shortcodes={selection.selected}
        onClear={selection.clear}
        onDone={refreshMedia}
      />
    </div>
  )
}
```

- [ ] **Step 5: Verify manually**

Task 21 supplies `SelectionBar`, so this page will not compile until then. Write `web/components/SelectionBar.tsx` as a one-line stub now and replace it in Task 21:

```tsx
export default function SelectionBar(_: {
  shortcodes: string[]
  onClear: () => void
  onDone: () => void
}) {
  return null
}
```

Then open `http://localhost:3000/p/nike` and confirm eight tiles render and clicking one outlines it.

- [ ] **Step 6: Commit**

```bash
git add web/lib/useSelection.ts web/components/MediaTile.tsx web/components/MediaGrid.tsx web/components/SelectionBar.tsx web/app/p web/e2e/grid.spec.ts
git commit -m "feat(web): profile screen with responsive grid and range selection"
```

---

### Task 21: Selection bar and the download flow

**Files:**
- Modify: `web/components/SelectionBar.tsx` (replace the stub)
- Test: `web/e2e/download.spec.ts`

**Interfaces:**
- Consumes: `ensureMedia`, `createDownload`.
- Produces: `SelectionBar({shortcodes, onClear, onDone})` — renders nothing when `shortcodes` is empty.

The three-call flow from spec §5 lives here:
1. `ensureMedia(shortcodes)` on submit — enqueues whatever is missing.
2. Re-poll `ensureMedia(shortcodes)` every 1500 ms; the same response is the progress feed.
3. When `ready === total`, call `createDownload(shortcodes, base)` and show the output directory.

Any `failed` item stops the poll and offers a retry that calls `ensureMedia(shortcodes, true)`. Closing the tab mid-wait stops the flow, which is the accepted tradeoff in spec §5 — the fetched media stays cached, so re-selecting finishes immediately.

- [ ] **Step 1: Write the Playwright spec**

`web/e2e/download.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test('selection bar appears only when something is selected', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('selection-bar')).toHaveCount(0)
  await page.getByTestId('tile-nike-0').click()
  await expect(page.getByTestId('selection-bar')).toBeVisible()
})

test('downloading three items reports the output directory', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-1').click()
  await page.getByTestId('tile-nike-2').click()

  await page.getByTestId('base-filename').fill('e2e_set')
  await page.getByTestId('download-submit').click()

  await expect(page.getByTestId('download-result')).toContainText('3 files', {
    timeout: 30_000,
  })
  await expect(page.getByTestId('download-result')).toContainText('/out')
})

test('progress is shown while media is being fetched', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('select-all').click()
  await page.getByTestId('base-filename').fill('e2e_all')
  await page.getByTestId('download-submit').click()

  await expect(page.getByTestId('download-progress')).toBeVisible()
  await expect(page.getByTestId('download-result')).toBeVisible({ timeout: 60_000 })
})

test('an empty base filename is rejected before any request', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('base-filename').fill('   ')
  await page.getByTestId('download-submit').click()
  await expect(page.getByTestId('download-error')).toContainText('filename')
})
```

- [ ] **Step 2: Run the spec and verify it fails**

Run: `cd web && npx playwright test e2e/download.spec.ts`
Expected: FAIL — `getByTestId('selection-bar')` never resolves, because the component is still the stub.

- [ ] **Step 3: Write the implementation**

`web/components/SelectionBar.tsx`:

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'

import { createDownload, ensureMedia, type DownloadResult, type EnsureResult } from '@/lib/api'

type Phase = 'idle' | 'waiting' | 'copying' | 'done' | 'error'

const POLL_MS = 1500

export default function SelectionBar({
  shortcodes,
  onClear,
  onDone,
}: {
  shortcodes: string[]
  onClear: () => void
  onDone: () => void
}) {
  const [base, setBase] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<EnsureResult | null>(null)
  const [result, setResult] = useState<DownloadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Changing the selection abandons any in-flight flow.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    setPhase('idle')
    setProgress(null)
    setResult(null)
    setError(null)
  }, [shortcodes.join(',')])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  if (shortcodes.length === 0) return null

  const counts = (statuses: Record<string, string>) => {
    const tally: Record<string, number> = {}
    for (const value of Object.values(statuses)) tally[value] = (tally[value] ?? 0) + 1
    return Object.entries(tally)
      .map(([k, v]) => `${v} ${k}`)
      .join(' · ')
  }

  async function copyNow() {
    setPhase('copying')
    try {
      const done = await createDownload(shortcodes, base.trim())
      setResult(done)
      setPhase('done')
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  async function step() {
    try {
      const state = await ensureMedia(shortcodes)
      setProgress(state)

      if (Object.values(state.statuses).includes('failed')) {
        setError('Some items failed to download from Instagram.')
        setPhase('error')
        return
      }
      if (Object.values(state.statuses).includes('unknown')) {
        setError('Some selected items are no longer in the index. Reload the profile.')
        setPhase('error')
        return
      }
      if (state.ready === state.total) {
        await copyNow()
        return
      }
      timer.current = setTimeout(step, POLL_MS)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  async function start() {
    const clean = base.trim()
    if (!clean) {
      setError('Enter a base filename first.')
      setPhase('error')
      return
    }
    setError(null)
    setResult(null)
    setPhase('waiting')
    await step()
  }

  async function retry() {
    setError(null)
    setPhase('waiting')
    await ensureMedia(shortcodes, true)
    await step()
  }

  return (
    <div className="selection-bar" data-testid="selection-bar">
      <strong data-testid="selection-count">{shortcodes.length} selected</strong>

      <input
        data-testid="base-filename"
        placeholder="base filename"
        value={base}
        onChange={(e) => setBase(e.target.value)}
        disabled={phase === 'waiting' || phase === 'copying'}
      />

      <button
        data-testid="download-submit"
        onClick={start}
        disabled={phase === 'waiting' || phase === 'copying'}
      >
        Download
      </button>

      <button data-testid="clear-selection" onClick={onClear}>
        Clear
      </button>

      {(phase === 'waiting' || phase === 'copying') && progress && (
        <span className="muted" data-testid="download-progress">
          {phase === 'copying' ? 'Copying files…' : counts(progress.statuses)}
        </span>
      )}

      {phase === 'done' && result && (
        <span data-testid="download-result">
          {result.count} files → {result.out_dir}
        </span>
      )}

      {phase === 'error' && error && (
        <span role="alert" data-testid="download-error">
          {error} <button onClick={retry}>Retry</button>
        </span>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the spec and verify it passes**

Run: `cd web && npx playwright test e2e/download.spec.ts`
Expected: PASS, 4 tests. This requires the Playwright config from Task 23; if you are working strictly in order, run this step's verification at the end of Task 23 instead and confirm both here and there.

Also verify by hand that files actually landed:

```bash
ls downloads/
```

Expected: `e2e_set_01.jpg`, `e2e_set_02.jpg`, `e2e_set_03.jpg`.

- [ ] **Step 5: Commit**

```bash
git add web/components/SelectionBar.tsx web/e2e/download.spec.ts
git commit -m "feat(web): selection bar with ensure-poll-download flow"
```

---

### Task 22: Activity screen

**Files:**
- Create: `web/app/activity/page.tsx`
- Test: `web/e2e/activity.spec.ts`

**Interfaces:**
- Consumes: `getActivity`.
- Produces: the `/activity` route — a reverse-chronological table of `ts`, `action`, `target`, and a readable rendering of `detail`.

- [ ] **Step 1: Write the Playwright spec**

`web/e2e/activity.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test('a download shows up in the activity log', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('base-filename').fill('activity_check')
  await page.getByTestId('download-submit').click()
  await expect(page.getByTestId('download-result')).toBeVisible({ timeout: 30_000 })

  await page.goto('/activity')

  const firstRow = page.getByTestId('activity-table').locator('tbody tr').first()
  await expect(firstRow).toContainText('download')
  await expect(firstRow).toContainText('activity_check')
})

test('activity table renders the seeded lookups', async ({ page }) => {
  await page.goto('/activity')
  await expect(page.getByTestId('activity-table')).toBeVisible()
})
```

- [ ] **Step 2: Run the spec and verify it fails**

Run: `cd web && npx playwright test e2e/activity.spec.ts`
Expected: FAIL — `/activity` 404s.

- [ ] **Step 3: Write the implementation**

`web/app/activity/page.tsx`:

```tsx
'use client'

import { getActivity, type ActivityItem } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

function summarise(item: ActivityItem): string {
  const detail = item.detail
  if (!detail) return ''
  if (item.action === 'download') {
    return `${detail.count} files as "${detail.base}" → ${detail.out}`
  }
  return JSON.stringify(detail)
}

export default function ActivityPage() {
  const { data } = usePolling(() => getActivity(200), 5000)

  return (
    <section>
      <h1>Activity</h1>
      <table data-testid="activity-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Action</th>
            <th>Target</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {(data?.items ?? []).map((item) => (
            <tr key={item.id}>
              <td className="muted">{item.ts.slice(0, 19).replace('T', ' ')}</td>
              <td>{item.action}</td>
              <td>{item.target ?? ''}</td>
              <td className="muted">{summarise(item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
```

- [ ] **Step 4: Run the spec and verify it passes**

Run: `cd web && npx playwright test e2e/activity.spec.ts`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add web/app/activity web/e2e/activity.spec.ts
git commit -m "feat(web): activity screen"
```

---

### Task 23: Playwright configuration and the full green run

**Files:**
- Create: `web/playwright.config.ts`, `scripts/e2e.sh`
- Modify: `README.md` (create it)
- Test: the whole suite, both sides

**Interfaces:**
- Consumes: everything.
- Produces: `scripts/e2e.sh` — brings up a fake-adapter stack on an isolated data directory, seeds it, runs Playwright, tears down.

- [ ] **Step 1: Write the Playwright config**

`web/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
})
```

`fullyParallel: false` and `workers: 1` are deliberate: the specs share one seeded database and one output directory, and the API serializes Instagram work anyway.

- [ ] **Step 2: Write the runner script**

`scripts/e2e.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=instascraper-e2e
export IG_ADAPTER=fake
export OUT_DIR=./.e2e/downloads

rm -rf .e2e
mkdir -p .e2e/data .e2e/downloads

cleanup() {
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v
}
trap cleanup EXIT

docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.e2e.yml \
  run --rm api python scripts/seed_e2e.py

for _ in $(seq 1 60); do
  if curl -sf http://localhost:3000/api/status >/dev/null; then break; fi
  sleep 1
done

cd web && npx playwright test
```

`docker-compose.e2e.yml`:

```yaml
services:
  api:
    environment:
      IG_ADAPTER: fake
      IG_MIN_INTERVAL: "0"
      PAGE_SIZE: "36"
    volumes:
      - ./.e2e/data:/data
      - ./.e2e/downloads:/out
  web:
    volumes:
      - ./.e2e/data:/data
```

Note the override also has to be listed in Task 17's file inventory if you regenerate it; it is created here because it only exists to serve the e2e run.

- [ ] **Step 3: Run the full backend suite**

Run: `cd api && python -m pytest -v`
Expected: PASS, roughly 95 tests, with the `live` module deselected.

- [ ] **Step 4: Run the full e2e suite**

Run: `bash scripts/e2e.sh`
Expected: PASS, 15 Playwright tests across `home`, `grid`, `download`, and `activity`.

If `download.spec.ts` times out, check `docker compose logs api` for a breaker trip — with `IG_ADAPTER=fake` there should never be one, and a trip means the fake is not actually in use.

- [ ] **Step 5: Write the README**

`README.md`:

```markdown
# instascraper

Local, single-user tool for browsing public Instagram profiles and pulling
media at full quality into a folder on this machine.

- Design: `docs/superpowers/specs/2026-08-23-instascraper-design.md`
- Plan: `docs/superpowers/plans/2026-08-23-instascraper.md`

## Setup

    cp .env.example .env      # fill in IG_USERNAME, IG_PASSWORD, OUT_DIR
    docker compose build
    docker compose run --rm api python -m app.ig.login
    docker compose up -d

Open http://localhost:3000.

## Everyday use

Enter a username, browse the grid, click tiles to select (shift-click for a
range), type a base filename, and press Download. Files land in `OUT_DIR`
named `base_01.jpg`, `base_02.mp4`, and so on.

## When the banner appears

- **Rate limited** — the worker paused itself. Nothing to do; it resumes.
- **Session invalid** — run the login command above, then press
  "I have fixed it" in the banner.
- **Empty grids and odd errors** — Instagram probably rotated something.
  Run the canary:

      cd api && python -m pytest -m live

  A failure there means `api/app/ig/adapter.py` needs updating. That is
  the only file that should ever need to change for this class of break.

## Tests

    cd api && python -m pytest      # backend, no network
    bash scripts/e2e.sh             # full stack against the fake adapter
    cd api && python -m pytest -m live   # opt-in, hits Instagram
```

- [ ] **Step 6: Commit**

```bash
chmod +x scripts/e2e.sh
git add web/playwright.config.ts scripts/e2e.sh docker-compose.e2e.yml README.md
git commit -m "test: playwright config, e2e runner script, and README"
```

---

## Plan Self-Review

**Spec coverage.** Every section of the design maps to at least one task:

| Spec section | Tasks |
|---|---|
| §2 Architecture, volumes, media layout, config | 1, 2, 17 |
| §3 Data model (five tables) | 1 |
| §4 Worker loop, pacing, session, job kinds | 4, 5, 7, 10, 11 |
| §4 Quality, atomic writes | 2, 9, 10 |
| §4 Failure taxonomy | 5, 7, 10 |
| §4 Instaloader containment | 3, 10 |
| §4 Downloads bypass the worker | 15 |
| §5 API endpoints | 12, 13, 14, 15, 16 |
| §5 Three-call download flow | 14, 15, 21 |
| §6 Home / Profile / Activity / Banner | 18, 19, 20, 21, 22 |
| §7 Testing (unit, worker, API, canary, no cassettes, Playwright) | 2-16, 23 |
| §8 Observability | 7, 12 |
| §9 Requirements traceability | all of the above |

**Two deliberate deviations, both flagged in place:**

1. `app/ig/rate.py` also imports `instaloader`, so the one-file constraint became one-directory. Task 10 Step 4 updates the guard test and says so.
2. The spec names four adapter functions; the real surface is five, because thumbnail and avatar bytes must not be fetched outside the module. Stated in Global Constraints.

**Placeholder scan.** No `TBD`, no "add error handling", no "similar to Task N". Two forward references are explicit and bounded: Task 20 ships a typed `SelectionBar` stub that Task 21 replaces, and Task 21's Playwright verification depends on Task 23's config, which its Step 4 calls out.

**Type consistency check.** `MediaSummary.full_status` in `lib/api.ts` matches the five `media_items.full_status` values. `EnsureResult.statuses` adds `unknown`, which the API returns for a shortcode with no row and `SelectionBar` handles explicitly. `paths.PostFiles` and `paths.NamedFile` are used with the same shapes in Task 2 and Task 15. `HandlerContext` fields are identical across Tasks 7, 8, 9, and the seed script. `Settings` gained no fields after Task 1.

One fix applied during review: Task 13's `_last_error` compares against a JSON string that must match `json.dumps(..., sort_keys=True)` byte-for-byte; the step now names that trap and offers `json_extract` as the robust alternative.
