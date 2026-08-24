# Instagram Graph API Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Instaloader adapter with a `GraphAdapter` built on Meta's Business Discovery endpoint, so instascraper can fetch real public Business and Creator accounts.

**Architecture:** A new `GraphAdapter` satisfies the existing `IgAdapter` protocol, so the worker, database, HTTP API and web UI are untouched. Business Discovery has no per-media endpoint, so media URLs are captured during page fetch, persisted, and silently refreshed by a bounded re-listing when Meta's CDN expires them. Mapping logic lives in a separate pure module tested against recorded fixtures.

**Tech Stack:** Python 3.12, FastAPI, SQLite, `httpx` (already a dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-instagram-graph-api-design.md`

## Global Constraints

- **No new runtime dependencies.** The Graph client uses `httpx`, already pinned in `api/requirements.txt`. Removing Instaloader also removes `requests`.
- **The token never appears in a URL.** It travels only in an `Authorization: Bearer` header. Never as an `access_token` query parameter.
- **The token never appears in logs, the `activity_log` table, or a committed fixture.** All error text echoed from Meta passes through a redaction guard.
- **Recorded fixtures are redacted before commit:** token, the operator's own IG user id, and `fbtrace_id`.
- **No test in the default suite touches the network.** The live canary is skipped unless `IG_GRAPH_TOKEN` is set.
- **`IG_GRAPH_VERSION` is a required env var with no source-level default.** Never hardcode a Graph API version.
- **`child_idx` convention:** `0` for a single-media post, `1..N` for carousel children. Matches `paths.full_filename` and `FakeAdapter`.
- **The five-case error model does not grow.** Everything maps onto `IgNotFound`, `IgPrivate`, `IgRateLimited`, `IgChallenge`, `IgTransient`.
- Work happens on branch `feat/graph-api-adapter`.

---

### Task 1: Media source types and the `fetch_media` hint

Widens the port so a post can carry the media URLs it saw, and so `fetch_media` can learn which account a post belongs to. Both additions are defaulted, so no existing caller changes behaviour.

**Files:**
- Modify: `api/app/ig/types.py`
- Modify: `api/app/ig/fake.py:139` (`FakeAdapter.fetch_media`)
- Modify: `api/app/ig/adapter.py:172` (`InstaloaderAdapter.fetch_media`)
- Test: `api/tests/test_ig_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MediaSource(child_idx: int, url: str, mime: str, is_video: bool)`, `MediaHint(username: str, sources: tuple[MediaSource, ...], captured_at: str)`, `IgPost.sources: tuple[MediaSource, ...]` defaulting to `()`, and the protocol signature `fetch_media(shortcode: str, dest_dir: Path, hint: MediaHint | None = None) -> list[SavedFile]`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_ig_contract.py`:

```python
def test_igpost_carries_media_sources():
    src = t.MediaSource(child_idx=0, url="https://cdn/x.jpg", mime="image/jpeg", is_video=False)
    post = t.IgPost(
        shortcode="abc",
        kind="image",
        taken_at_iso="2026-01-01T00:00:00+00:00",
        caption="",
        is_video=False,
        child_count=1,
        thumb_url="https://cdn/t.jpg",
        ig_url="https://instagram.com/p/abc/",
        sources=(src,),
    )
    assert post.sources[0].url == "https://cdn/x.jpg"


def test_igpost_sources_default_to_empty():
    post = t.IgPost(
        shortcode="abc",
        kind="image",
        taken_at_iso="2026-01-01T00:00:00+00:00",
        caption="",
        is_video=False,
        child_count=1,
        thumb_url="https://cdn/t.jpg",
        ig_url="https://instagram.com/p/abc/",
    )
    assert post.sources == ()


def test_fake_fetch_media_accepts_and_ignores_a_hint(tmp_path):
    fake = FakeAdapter()
    fake.add_profile("nike")
    fake.add_posts("nike", count=1)
    hint = t.MediaHint(username="nike", sources=(), captured_at="2026-01-01T00:00:00+00:00")
    saved = fake.fetch_media("nike-0", tmp_path, hint)
    assert [s.child_idx for s in saved] == [0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_ig_contract.py -k "sources or hint" -v`
Expected: FAIL with `AttributeError: module 'app.ig.types' has no attribute 'MediaSource'`

- [ ] **Step 3: Write minimal implementation**

In `api/app/ig/types.py`, add above `IgPost`:

```python
@dataclass(frozen=True)
class MediaSource:
    """One downloadable file belonging to a post.

    `child_idx` is 0 for a single-media post and 1..N for carousel children,
    matching `paths.full_filename`.
    """

    child_idx: int
    url: str
    mime: str
    is_video: bool


@dataclass(frozen=True)
class MediaHint:
    """What the handler knows about a post that the adapter cannot look up.

    Business Discovery has no per-media endpoint, so refreshing an expired
    URL means re-listing the owning profile. The adapter has no database
    access, so the handler passes the owner and the last known URLs here.
    """

    username: str
    sources: tuple[MediaSource, ...]
    captured_at: str
```

Add the field to `IgPost` (last, so it may be defaulted):

```python
    sources: tuple[MediaSource, ...] = ()
```

Change the protocol member in `IgAdapter`:

```python
    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: "MediaHint | None" = None
    ) -> list[SavedFile]: ...
```

In `api/app/ig/fake.py`, change the signature only:

```python
    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: t.MediaHint | None = None
    ) -> list[t.SavedFile]:
```

In `api/app/ig/adapter.py`, the same:

```python
    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: t.MediaHint | None = None
    ) -> list[t.SavedFile]:
```

Neither implementation reads `hint`. Both ignore it deliberately — the fake has its data in memory, and Instaloader has a per-post endpoint.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS, whole suite green — the additions are backward compatible.

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/types.py api/app/ig/fake.py api/app/ig/adapter.py api/tests/test_ig_contract.py
git commit -m "feat(api): let a post carry its media sources and a fetch hint"
```

---

### Task 2: Persist media URLs on `media_items`

Adds the two columns the refresh strategy needs, plus the migration helper the project has never had.

**Files:**
- Modify: `api/app/schema.sql`
- Modify: `api/app/db.py`
- Modify: `api/app/main.py:36`
- Test: `api/tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `db.migrate(conn) -> None`, and the columns `media_items.src_urls TEXT` and `media_items.src_urls_at TEXT`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_db.py`:

```python
def test_migrate_adds_src_url_columns_to_an_old_database(settings):
    conn = db.new_conn(settings)
    conn.execute(
        "CREATE TABLE media_items ("
        " shortcode TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,"
        " taken_at TEXT NOT NULL, caption TEXT, is_video INTEGER NOT NULL,"
        " child_count INTEGER NOT NULL DEFAULT 1, full_status TEXT NOT NULL DEFAULT 'none',"
        " full_error TEXT, ig_url TEXT NOT NULL, discovered_at TEXT NOT NULL)"
    )

    db.migrate(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(media_items)")}
    assert "src_urls" in columns
    assert "src_urls_at" in columns
    conn.close()


def test_migrate_is_idempotent(conn):
    db.migrate(conn)
    db.migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(media_items)")}
    assert "src_urls" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_db.py -k migrate -v`
Expected: FAIL with `AttributeError: module 'app.db' has no attribute 'migrate'`

- [ ] **Step 3: Write minimal implementation**

In `api/app/schema.sql`, add the two columns to the `media_items` definition, after `ig_url`:

```sql
  src_urls      TEXT,
  src_urls_at   TEXT,
```

In `api/app/db.py`, add below `init_schema`:

```python
# SQLite has no ADD COLUMN IF NOT EXISTS, and schema.sql only ever creates
# tables that do not exist yet. Columns added to an existing table therefore
# need this. Keyed by table, then by column.
_ADDED_COLUMNS = {
    "media_items": {
        "src_urls": "ALTER TABLE media_items ADD COLUMN src_urls TEXT",
        "src_urls_at": "ALTER TABLE media_items ADD COLUMN src_urls_at TEXT",
    },
}


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema. Idempotent."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table does not exist yet; schema.sql just created it
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(ddl)
```

In `api/app/main.py`, immediately after the existing `db.init_schema(conn)` call:

```python
        db.migrate(conn)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/schema.sql api/app/db.py api/app/main.py api/tests/test_db.py
git commit -m "feat(api): persist media source urls and add a column migration step"
```

---

### Task 3: Map a Business Discovery profile

First half of the pure mapping module. No network, no adapter, no settings.

**Files:**
- Create: `api/app/ig/graph_map.py`
- Create: `api/tests/fixtures/graph/profile.json`
- Test: `api/tests/test_graph_map.py`

**Interfaces:**
- Consumes: `t.IgProfile` from Task 1's module.
- Produces: `profile_from_payload(payload: dict) -> t.IgProfile` and `shortcode_from_permalink(permalink: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/fixtures/graph/profile.json`. This is a redacted capture — the operator's own node id is `SELF`:

```json
{
  "business_discovery": {
    "id": "17841400000000000",
    "ig_id": 1234567,
    "username": "nike",
    "name": "Nike",
    "biography": "Just Do It.",
    "followers_count": 291400000,
    "media_count": 1669,
    "profile_picture_url": "https://scontent.cdninstagram.com/v/t51.2885-19/avatar.jpg"
  },
  "id": "SELF"
}
```

Create `api/tests/test_graph_map.py`:

```python
import json
from pathlib import Path

import pytest

from app.ig import graph_map, types as t

FIXTURES = Path(__file__).parent / "fixtures" / "graph"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_profile_maps_every_field():
    profile = graph_map.profile_from_payload(load("profile.json"))
    assert profile.username == "nike"
    assert profile.user_id == "17841400000000000"
    assert profile.full_name == "Nike"
    assert profile.biography == "Just Do It."
    assert profile.post_count == 1669
    assert profile.avatar_url.endswith("avatar.jpg")


def test_profile_is_never_private():
    """Business Discovery only returns public Business/Creator accounts."""
    assert graph_map.profile_from_payload(load("profile.json")).is_private is False


def test_profile_tolerates_missing_optional_fields():
    payload = {"business_discovery": {"id": "1", "username": "x"}}
    profile = graph_map.profile_from_payload(payload)
    assert profile.full_name == ""
    assert profile.biography == ""
    assert profile.post_count == 0


@pytest.mark.parametrize(
    "permalink,expected",
    [
        ("https://www.instagram.com/p/DcVY5dZm_Pv/", "DcVY5dZm_Pv"),
        ("https://www.instagram.com/reel/Db6EzJxRewC/", "Db6EzJxRewC"),
        ("https://www.instagram.com/tv/DbJCoXguNF5/", "DbJCoXguNF5"),
    ],
)
def test_shortcode_parses_from_permalink(permalink, expected):
    assert graph_map.shortcode_from_permalink(permalink) == expected


def test_shortcode_rejects_an_unrecognised_permalink():
    with pytest.raises(ValueError):
        graph_map.shortcode_from_permalink("https://example.com/nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'graph_map'`

- [ ] **Step 3: Write minimal implementation**

Create `api/app/ig/graph_map.py`:

```python
"""Pure mapping from Meta Business Discovery JSON onto our own types.

Deliberately free of network, settings and side effects: this is the code
that breaks when Meta reshapes a response, and purity is what lets it be
tested against recorded fixtures.
"""

import re

from app.ig import types as t

_PERMALINK = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def shortcode_from_permalink(permalink: str) -> str:
    match = _PERMALINK.search(permalink or "")
    if match is None:
        raise ValueError(f"no shortcode in permalink: {permalink!r}")
    return match.group(1)


def profile_from_payload(payload: dict) -> t.IgProfile:
    bd = payload["business_discovery"]
    return t.IgProfile(
        username=bd["username"],
        user_id=str(bd.get("id") or ""),
        full_name=bd.get("name") or "",
        biography=bd.get("biography") or "",
        # Business Discovery only ever returns public Business/Creator
        # accounts. A private one is an error, not a private-looking result.
        is_private=False,
        post_count=int(bd.get("media_count") or 0),
        avatar_url=bd.get("profile_picture_url") or "",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_map.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph_map.py api/tests/test_graph_map.py api/tests/fixtures/graph/profile.json
git commit -m "feat(api): map a Business Discovery profile onto IgProfile"
```

---

### Task 4: Map Business Discovery media

Second half of the mapping module: posts, carousels, video, reels, and the paging cursor.

**Files:**
- Modify: `api/app/ig/graph_map.py`
- Create: `api/tests/fixtures/graph/media_page.json`
- Create: `api/tests/fixtures/graph/media_last_page.json`
- Test: `api/tests/test_graph_map.py`

**Interfaces:**
- Consumes: `shortcode_from_permalink` from Task 3, `MediaSource` from Task 1.
- Produces: `post_from_node(node: dict) -> t.IgPost` and `page_from_payload(payload: dict) -> t.IgPage`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/fixtures/graph/media_page.json` — one image, one video, one carousel:

```json
{
  "business_discovery": {
    "media": {
      "data": [
        {
          "id": "1",
          "caption": "an image",
          "media_type": "IMAGE",
          "media_url": "https://scontent.cdninstagram.com/img1.jpg",
          "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
          "timestamp": "2026-08-20T14:03:11+0000"
        },
        {
          "id": "2",
          "caption": "a reel",
          "media_type": "VIDEO",
          "media_product_type": "REELS",
          "media_url": "https://scontent.cdninstagram.com/vid2.mp4",
          "thumbnail_url": "https://scontent.cdninstagram.com/thumb2.jpg",
          "permalink": "https://www.instagram.com/reel/BBBBBBBBBBB/",
          "timestamp": "2026-08-19T09:00:00+0000"
        },
        {
          "id": "3",
          "caption": "a carousel",
          "media_type": "CAROUSEL_ALBUM",
          "media_url": "https://scontent.cdninstagram.com/album3.jpg",
          "permalink": "https://www.instagram.com/p/CCCCCCCCCCC/",
          "timestamp": "2026-08-18T09:00:00+0000",
          "children": {
            "data": [
              {"id": "3a", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/c1.jpg"},
              {"id": "3b", "media_type": "VIDEO", "media_url": "https://scontent.cdninstagram.com/c2.mp4", "thumbnail_url": "https://scontent.cdninstagram.com/c2.jpg"}
            ]
          }
        }
      ],
      "paging": {
        "cursors": {"after": "CURSOR_AFTER_1"},
        "next": "https://graph.facebook.com/next-page"
      }
    }
  },
  "id": "SELF"
}
```

Create `api/tests/fixtures/graph/media_last_page.json` — a final page, cursor present but no `next`:

```json
{
  "business_discovery": {
    "media": {
      "data": [
        {
          "id": "9",
          "caption": "last one",
          "media_type": "IMAGE",
          "media_url": "https://scontent.cdninstagram.com/img9.jpg",
          "permalink": "https://www.instagram.com/p/ZZZZZZZZZZZ/",
          "timestamp": "2026-01-01T00:00:00+0000"
        }
      ],
      "paging": {"cursors": {"after": "CURSOR_AFTER_LAST"}}
    }
  },
  "id": "SELF"
}
```

Append to `api/tests/test_graph_map.py`:

```python
def test_image_post_maps_to_a_single_source():
    page = graph_map.page_from_payload(load("media_page.json"))
    post = page.posts[0]
    assert post.shortcode == "AAAAAAAAAAA"
    assert post.kind == "image"
    assert post.is_video is False
    assert post.child_count == 1
    assert post.thumb_url.endswith("img1.jpg")
    assert post.sources == (
        t.MediaSource(0, "https://scontent.cdninstagram.com/img1.jpg", "image/jpeg", False),
    )


def test_timestamp_is_normalised_to_iso_with_a_colon_offset():
    post = graph_map.page_from_payload(load("media_page.json")).posts[0]
    assert post.taken_at_iso == "2026-08-20T14:03:11+00:00"


def test_reel_is_distinguished_from_plain_video_by_its_permalink():
    post = graph_map.page_from_payload(load("media_page.json")).posts[1]
    assert post.kind == "reel"
    assert post.is_video is True
    # A video's thumbnail is the still, but its source is the MP4.
    assert post.thumb_url.endswith("thumb2.jpg")
    assert post.sources[0].url.endswith("vid2.mp4")
    assert post.sources[0].mime == "video/mp4"


def test_carousel_children_become_one_indexed_sources():
    post = graph_map.page_from_payload(load("media_page.json")).posts[2]
    assert post.kind == "carousel"
    assert post.child_count == 2
    assert [s.child_idx for s in post.sources] == [1, 2]
    assert post.sources[0].mime == "image/jpeg"
    assert post.sources[1].mime == "video/mp4"
    assert post.sources[1].is_video is True


def test_page_reports_the_after_cursor_when_more_remain():
    assert graph_map.page_from_payload(load("media_page.json")).next_cursor == "CURSOR_AFTER_1"


def test_final_page_reports_exhaustion_despite_carrying_a_cursor():
    """Meta still sends an `after` cursor on the last page; only `next` is
    proof that another page exists."""
    assert graph_map.page_from_payload(load("media_last_page.json")).next_cursor is None


def test_absent_media_edge_is_an_empty_exhausted_page():
    page = graph_map.page_from_payload({"business_discovery": {"username": "x"}})
    assert page.posts == []
    assert page.next_cursor is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_map.py -v`
Expected: FAIL with `AttributeError: module 'app.ig.graph_map' has no attribute 'page_from_payload'`

- [ ] **Step 3: Write minimal implementation**

Append to `api/app/ig/graph_map.py`:

```python
from datetime import datetime

_KIND = {"IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}


def _mime(media_type: str) -> str:
    # Meta does not return a content type in a listing, so it is derived.
    return "video/mp4" if media_type == "VIDEO" else "image/jpeg"


def _children(node: dict) -> list[dict]:
    return (node.get("children") or {}).get("data") or []


def _timestamp(raw: str) -> str:
    """Meta sends `+0000`; the rest of the app stores `+00:00`."""
    return datetime.fromisoformat(raw).isoformat()


def _sources(node: dict) -> tuple[t.MediaSource, ...]:
    children = _children(node)
    if children:
        return tuple(
            t.MediaSource(
                child_idx=index,
                url=child.get("media_url") or "",
                mime=_mime(child.get("media_type", "")),
                is_video=child.get("media_type") == "VIDEO",
            )
            for index, child in enumerate(children, start=1)
        )
    media_type = node.get("media_type", "")
    return (
        t.MediaSource(
            child_idx=0,
            url=node.get("media_url") or "",
            mime=_mime(media_type),
            is_video=media_type == "VIDEO",
        ),
    )


def _thumb_url(node: dict) -> str:
    if node.get("media_type") == "VIDEO":
        return node.get("thumbnail_url") or node.get("media_url") or ""
    children = _children(node)
    if children and not node.get("media_url"):
        first = children[0]
        if first.get("media_type") == "VIDEO":
            return first.get("thumbnail_url") or ""
        return first.get("media_url") or ""
    return node.get("media_url") or ""


def post_from_node(node: dict) -> t.IgPost:
    permalink = node.get("permalink") or ""
    media_type = node.get("media_type", "")
    kind = _KIND.get(media_type, "image")
    if kind == "video" and "/reel/" in permalink:
        kind = "reel"
    children = _children(node)
    return t.IgPost(
        shortcode=shortcode_from_permalink(permalink),
        kind=kind,
        taken_at_iso=_timestamp(node["timestamp"]),
        caption=node.get("caption") or "",
        is_video=media_type == "VIDEO",
        child_count=len(children) or 1,
        thumb_url=_thumb_url(node),
        ig_url=permalink,
        sources=_sources(node),
    )


def page_from_payload(payload: dict) -> t.IgPage:
    media = (payload.get("business_discovery") or {}).get("media") or {}
    posts = [post_from_node(node) for node in media.get("data") or []]
    paging = media.get("paging") or {}
    # An `after` cursor is present even on the final page. Only the presence
    # of `next` proves another page exists.
    cursor = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
    return t.IgPage(posts=posts, next_cursor=cursor)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_map.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph_map.py api/tests/test_graph_map.py api/tests/fixtures/graph/
git commit -m "feat(api): map Business Discovery media onto IgPost and IgPage"
```

---

### Task 5: Graph HTTP client and error classification

The transport and the translation of Meta's error envelope into the five cases. No adapter yet.

**Files:**
- Create: `api/app/ig/graph.py`
- Test: `api/tests/test_graph_errors.py`

**Interfaces:**
- Consumes: `t.IgError` subclasses.
- Produces: `redact(text: str, token: str) -> str`, `usage_percent(headers: dict) -> float`, `classify(status: int, payload: dict, headers: dict | None = None, token: str = "") -> t.IgError`, and the transport contract `Callable[[str, dict], tuple[int, dict, dict]]` returning `(status, headers, json_body)`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_graph_errors.py`:

```python
import pytest

from app.ig import graph, types as t


def envelope(code, message="boom", subcode=None):
    error = {"message": message, "type": "OAuthException", "code": code}
    if subcode is not None:
        error["error_subcode"] = subcode
    return {"error": error}


@pytest.mark.parametrize("code", [190, 102, 200, 250, 299])
def test_auth_and_permission_codes_are_challenges(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgChallenge)


@pytest.mark.parametrize("code", [4, 17, 32, 613])
def test_throttling_codes_are_rate_limits(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgRateLimited)


@pytest.mark.parametrize("code", [1, 2])
def test_transient_meta_codes_are_transient(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgTransient)


def test_server_errors_are_transient():
    assert isinstance(graph.classify(503, {}), t.IgTransient)


def test_unknown_code_defaults_to_transient():
    assert isinstance(graph.classify(400, envelope(99999)), t.IgTransient)


def test_missing_user_is_not_found():
    exc = graph.classify(400, envelope(110, "Invalid user id"))
    assert isinstance(exc, t.IgNotFound)


def test_non_business_target_is_out_of_scope():
    exc = graph.classify(
        400, envelope(100, "The user is not an Instagram Business or Creator account")
    )
    assert isinstance(exc, t.IgPrivate)


def test_rate_limit_carries_the_wait_meta_asked_for():
    headers = {
        "x-business-use-case-usage": '{"1":[{"estimated_time_to_regain_access":7}]}'
    }
    exc = graph.classify(400, envelope(4), headers)
    assert isinstance(exc, t.IgRateLimited)
    assert exc.retry_after == 420.0


def test_rate_limit_without_an_estimate_has_no_retry_after():
    exc = graph.classify(400, envelope(4), {})
    assert exc.retry_after is None


def test_token_never_survives_into_an_error_message():
    exc = graph.classify(400, envelope(190, "Bad token SECRET123"), {}, token="SECRET123")
    assert "SECRET123" not in str(exc)
    assert "[redacted]" in str(exc)


def test_usage_percent_reads_the_highest_counter():
    headers = {"x-app-usage": '{"call_count":12,"total_cputime":91,"total_time":3}'}
    assert graph.usage_percent(headers) == 91.0


def test_usage_percent_is_zero_when_the_header_is_absent_or_junk():
    assert graph.usage_percent({}) == 0.0
    assert graph.usage_percent({"x-app-usage": "not json"}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_errors.py -v`
Expected: FAIL with `ImportError: cannot import name 'graph' from 'app.ig'`

- [ ] **Step 3: Write minimal implementation**

Create `api/app/ig/graph.py`:

```python
"""Meta Graph API (Business Discovery) adapter.

Business Discovery is a nested field on our own Instagram Business account
node, not a standalone endpoint, and it has no per-media lookup: media URLs
exist only inside a listing response.
"""

import json

from app.ig import types as t

_CHALLENGE_CODES = {102, 190}
_RATE_LIMIT_CODES = {4, 17, 32, 613}
_TRANSIENT_CODES = {1, 2}

# Meta has no dedicated code for "this target is not a Business account", so
# the message is the only signal. Confirmed against a real response in the
# task that adds the live canary.
_NOT_BUSINESS_HINTS = ("not an instagram business", "not a business", "business or creator")
_NOT_FOUND_HINTS = ("invalid user id", "does not exist", "cannot be found")


def redact(text: str, token: str) -> str:
    """Never let a token reach a log line, the activity table, or an error."""
    if token and token in text:
        return text.replace(token, "[redacted]")
    return text


def usage_percent(headers: dict) -> float:
    """Highest of Meta's three app-usage counters, as a percentage.

    Meta throttles on whichever counter saturates first, so the maximum is
    the only number worth acting on.
    """
    raw = (headers or {}).get("x-app-usage")
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return 0.0
    values = [data.get(k, 0) for k in ("call_count", "total_cputime", "total_time")]
    return float(max(values or [0]))


def _retry_after(headers: dict) -> float | None:
    """Meta sends no Retry-After, but throttling replies estimate the wait."""
    raw = (headers or {}).get("x-business-use-case-usage")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    for entries in data.values():
        for entry in entries or []:
            minutes = entry.get("estimated_time_to_regain_access")
            if minutes:
                return float(minutes) * 60.0
    return None


def classify(
    status: int, payload: dict, headers: dict | None = None, token: str = ""
) -> t.IgError:
    """Map a Meta failure onto the five cases the worker knows how to handle."""
    error = (payload or {}).get("error") or {}
    code = error.get("code")
    message = redact(error.get("message") or f"HTTP {status}", token)
    lowered = message.lower()

    if code in _CHALLENGE_CODES or (isinstance(code, int) and 200 <= code <= 299):
        return t.IgChallenge(message)
    if code in _RATE_LIMIT_CODES:
        return t.IgRateLimited(message, retry_after=_retry_after(headers or {}))
    if any(hint in lowered for hint in _NOT_BUSINESS_HINTS):
        return t.IgPrivate(message)
    if any(hint in lowered for hint in _NOT_FOUND_HINTS):
        return t.IgNotFound(message)
    if code in _TRANSIENT_CODES or status >= 500:
        return t.IgTransient(message)
    return t.IgTransient(message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_errors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph.py api/tests/test_graph_errors.py
git commit -m "feat(api): classify Meta Graph errors into the five adapter cases"
```

---

### Task 6: `GraphAdapter.fetch_profile` and `login`

The adapter class, its injected transport, the usage guard, and the first read.

**Files:**
- Modify: `api/app/ig/graph.py`
- Modify: `api/app/config.py`
- Modify: `api/tests/conftest.py`
- Test: `api/tests/test_graph_adapter.py`

**Interfaces:**
- Consumes: `classify`, `usage_percent`, `redact` from Task 5; `graph_map.profile_from_payload` from Task 3.
- Produces: `Settings.graph_token: str`, `.graph_user_id: str`, `.graph_version: str`, `.graph_refresh_pages: int`, `.graph_usage_limit: float`; and `GraphAdapter(settings, transport=None, fetcher=None)` with `.fetch_profile(username) -> t.IgProfile`, `.login() -> None`, and the protected helper `._get(fields: str) -> dict`. `transport(url: str, headers: dict) -> tuple[int, dict, dict]`; `fetcher(url: str) -> tuple[int, bytes]`.

This task owns the `Settings` fields because `Settings` is a frozen dataclass with no defaults: the moment five required fields appear, every construction site must supply them, so `conftest.py` changes in the same commit or the whole suite fails to collect.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_graph_adapter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -v`
Expected: FAIL with `TypeError: replace() got an unexpected keyword argument 'graph_token'` — the settings fields do not exist yet. Step 3 adds them first, then the adapter.

- [ ] **Step 3: Write minimal implementation**

First the configuration, because `Settings` is frozen and has no defaults — adding required fields breaks every construction site at once.

In `api/app/config.py`, add to the `Settings` dataclass:

```python
    graph_token: str
    graph_user_id: str
    graph_version: str
    graph_refresh_pages: int
    graph_usage_limit: float
```

and to `load_settings()`:

```python
        graph_token=os.environ.get("IG_GRAPH_TOKEN", ""),
        graph_user_id=os.environ.get("IG_GRAPH_USER_ID", ""),
        # Deliberately no source-level default: pinning a Graph version in
        # code means a Meta deprecation becomes a code change.
        graph_version=os.environ.get("IG_GRAPH_VERSION", ""),
        # How many pages deep to look when refreshing an expired media url.
        graph_refresh_pages=int(os.environ.get("IG_GRAPH_REFRESH_PAGES", "2")),
        graph_usage_limit=float(os.environ.get("IG_GRAPH_USAGE_LIMIT", "90")),
```

In `api/tests/conftest.py`, add the same five to the `Settings(...)` construction:

```python
        graph_token="",
        graph_user_id="",
        graph_version="v99.0",
        graph_refresh_pages=2,
        graph_usage_limit=90.0,
```

Then append to `api/app/ig/graph.py`:

```python
from urllib.parse import quote

import httpx

from app.config import Settings
from app.ig import graph_map

_BASE = "https://graph.facebook.com"
_PROFILE_FIELDS = (
    "id,ig_id,username,name,biography,followers_count,media_count,profile_picture_url"
)


def _httpx_transport(url: str, headers: dict) -> tuple[int, dict, dict]:
    response = httpx.get(url, headers=headers, timeout=30.0)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, {k.lower(): v for k, v in response.headers.items()}, body


def _httpx_fetcher(url: str) -> tuple[int, bytes]:
    response = httpx.get(url, timeout=60.0, follow_redirects=True)
    return response.status_code, response.content


class GraphAdapter:
    """Reads public Business and Creator accounts via Business Discovery."""

    def __init__(self, settings: Settings, transport=None, fetcher=None):
        self._settings = settings
        self._transport = transport or _httpx_transport
        self._fetcher = fetcher or _httpx_fetcher
        self._usage = 0.0

    # ---- transport -----------------------------------------------------
    def _get(self, fields: str) -> dict:
        if not self._settings.graph_token or not self._settings.graph_user_id:
            raise t.IgChallenge(
                "IG_GRAPH_TOKEN and IG_GRAPH_USER_ID must be set to use the Graph adapter."
            )
        # Refuse to spend a call we already know is close to the ceiling.
        if self._usage >= self._settings.graph_usage_limit:
            raise t.IgRateLimited(
                f"app usage at {self._usage:.0f}% of Meta's limit; backing off"
            )

        url = (
            f"{_BASE}/{self._settings.graph_version}/{self._settings.graph_user_id}"
            f"?fields={quote(fields, safe='(),{}.')}"
        )
        headers = {"Authorization": f"Bearer {self._settings.graph_token}"}
        try:
            status, response_headers, body = self._transport(url, headers)
        except t.IgError:
            raise
        except Exception as exc:
            raise t.IgTransient(redact(str(exc), self._settings.graph_token)) from exc

        self._usage = max(self._usage, usage_percent(response_headers))
        if status >= 400 or "error" in body:
            raise classify(status, body, response_headers, self._settings.graph_token)
        return body

    # ---- IgAdapter -----------------------------------------------------
    def login(self) -> None:
        """No interactive login exists; this validates the token instead."""
        self._get("id")

    def fetch_profile(self, username: str) -> t.IgProfile:
        payload = self._get(f"business_discovery.username({username}){{{_PROFILE_FIELDS}}}")
        return graph_map.profile_from_payload(payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_adapter.py tests/test_graph_errors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph.py api/app/config.py api/tests/conftest.py api/tests/test_graph_adapter.py
git commit -m "feat(api): add GraphAdapter with token validation and profile fetch"
```

---

### Task 7: `GraphAdapter.fetch_page`

Paging, the `limit` and `after` modifiers, and the cursor contract.

**Files:**
- Modify: `api/app/ig/graph.py`
- Test: `api/tests/test_graph_adapter.py`

**Interfaces:**
- Consumes: `_get` from Task 6, `graph_map.page_from_payload` from Task 4.
- Produces: `.fetch_page(username: str, cursor: str | None, limit: int) -> t.IgPage`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_graph_adapter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -k fetch_page -v`
Expected: FAIL with `AttributeError: 'GraphAdapter' object has no attribute 'fetch_page'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/app/ig/graph.py`, alongside `_PROFILE_FIELDS`:

```python
_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
    "permalink,timestamp,children{id,media_type,media_url,thumbnail_url}"
)
```

And the method on `GraphAdapter`:

```python
    def fetch_page(self, username: str, cursor: str | None, limit: int) -> t.IgPage:
        media = f"media.limit({limit})"
        if cursor:
            media += f".after({cursor})"
        payload = self._get(
            f"business_discovery.username({username}){{{media}{{{_MEDIA_FIELDS}}}}}"
        )
        return graph_map.page_from_payload(payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph.py api/tests/test_graph_adapter.py
git commit -m "feat(api): page a profile's media through Business Discovery"
```

---

### Task 8: The handler persists sources and builds the hint

Wires the new column into the worker so the adapter can be told what it needs.

**Files:**
- Modify: `api/app/worker/handlers.py:70-108` (`handle_page_fetch`), `:115-135` (`handle_media_fetch`)
- Test: `api/tests/test_handlers_media.py`, `api/tests/test_handlers_profile.py`

**Interfaces:**
- Consumes: `MediaSource` and `MediaHint` from Task 1, the `src_urls` columns from Task 2.
- Produces: `media_items.src_urls` holding a JSON array of `{child_idx, url, mime, is_video}`, and a `MediaHint` passed as the third argument to `adapter.fetch_media`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_handlers_profile.py`:

```python
def test_page_fetch_persists_media_sources(ctx_factory, conn):
    """The adapter cannot look a post up later, so the URLs are stored now."""
    from app.ig import types as t
    from app.worker.handlers import handle_page_fetch, handle_profile_sync

    ctx = ctx_factory()
    ctx.adapter.add_profile("nike", post_count=1)
    ctx.adapter.posts["nike"] = [
        t.IgPost(
            shortcode="s1",
            kind="image",
            taken_at_iso="2026-01-01T00:00:00+00:00",
            caption="",
            is_video=False,
            child_count=1,
            thumb_url="https://cdn.test/t.jpg",
            ig_url="https://instagram.com/p/s1/",
            sources=(t.MediaSource(0, "https://cdn.test/full.jpg", "image/jpeg", False),),
        )
    ]
    handle_profile_sync(ctx, {"username": "nike"})
    handle_page_fetch(ctx, {"username": "nike"})

    row = conn.execute("SELECT src_urls, src_urls_at FROM media_items WHERE shortcode='s1'").fetchone()
    stored = json.loads(row["src_urls"])
    assert stored == [
        {"child_idx": 0, "url": "https://cdn.test/full.jpg", "mime": "image/jpeg", "is_video": False}
    ]
    assert row["src_urls_at"]
```

Append to `api/tests/test_handlers_media.py`:

```python
def test_media_fetch_hands_the_adapter_a_hint(ctx_factory, conn):
    from app.ig import types as t
    from app.worker.handlers import handle_media_fetch

    seen = {}

    class Recording:
        def fetch_media(self, shortcode, dest_dir, hint=None):
            seen["hint"] = hint
            return []

    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike','2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at, src_urls, src_urls_at)"
        " VALUES ('s1','nike','image','2026-01-01T00:00:00+00:00',0,"
        " 'https://instagram.com/p/s1/','2026-01-01T00:00:00+00:00',?,?)",
        (
            json.dumps([{"child_idx": 0, "url": "https://cdn/f.jpg", "mime": "image/jpeg", "is_video": False}]),
            "2026-01-01T00:00:00+00:00",
        ),
    )

    ctx = ctx_factory(adapter=Recording())
    handle_media_fetch(ctx, {"shortcode": "s1"})

    hint = seen["hint"]
    assert hint.username == "nike"
    assert hint.sources == (t.MediaSource(0, "https://cdn/f.jpg", "image/jpeg", False),)


def test_media_fetch_hint_is_empty_when_nothing_was_stored(ctx_factory, conn):
    from app.worker.handlers import handle_media_fetch

    seen = {}

    class Recording:
        def fetch_media(self, shortcode, dest_dir, hint=None):
            seen["hint"] = hint
            return []

    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike','2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO media_items (shortcode, username, kind, taken_at, is_video,"
        " ig_url, discovered_at) VALUES ('s2','nike','image','2026-01-01T00:00:00+00:00',0,"
        " 'https://instagram.com/p/s2/','2026-01-01T00:00:00+00:00')"
    )

    ctx = ctx_factory(adapter=Recording())
    handle_media_fetch(ctx, {"shortcode": "s2"})

    assert seen["hint"].sources == ()
    assert seen["hint"].username == "nike"
```

Both files need `import json` at the top. If `ctx_factory` does not already exist in these test modules, reuse whatever `HandlerContext` construction they currently use — check the top of each file and follow the established pattern rather than inventing a new fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_handlers_media.py tests/test_handlers_profile.py -k "hint or sources" -v`
Expected: FAIL — `src_urls` is `None` and `hint` is `None`.

- [ ] **Step 3: Write minimal implementation**

At the top of `api/app/worker/handlers.py`:

```python
import json
```

In `handle_page_fetch`, replace the `media_items` insert with one that carries the sources:

```python
        sources_json = json.dumps(
            [
                {
                    "child_idx": s.child_idx,
                    "url": s.url,
                    "mime": s.mime,
                    "is_video": s.is_video,
                }
                for s in post.sources
            ]
        )
        ctx.conn.execute(
            "INSERT INTO media_items (shortcode, username, kind, taken_at, caption,"
            " is_video, child_count, ig_url, discovered_at, src_urls, src_urls_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(shortcode) DO UPDATE SET"
            " caption=excluded.caption, child_count=excluded.child_count,"
            " src_urls=excluded.src_urls, src_urls_at=excluded.src_urls_at",
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
                sources_json,
                now_iso(),
            ),
        )
```

In `handle_media_fetch`, build the hint before calling the adapter:

```python
    raw_sources = item["src_urls"] if "src_urls" in item.keys() else None
    sources = tuple(
        t.MediaSource(
            child_idx=int(entry["child_idx"]),
            url=entry["url"],
            mime=entry["mime"],
            is_video=bool(entry["is_video"]),
        )
        for entry in json.loads(raw_sources or "[]")
    )
    hint = t.MediaHint(
        username=item["username"],
        sources=sources,
        captured_at=(item["src_urls_at"] if "src_urls_at" in item.keys() else None) or "",
    )
```

and pass it:

```python
        saved_files = ctx.adapter.fetch_media(shortcode, dest_dir, hint)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS, whole suite green.

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/handlers.py api/tests/test_handlers_media.py api/tests/test_handlers_profile.py
git commit -m "feat(api): store media source urls and pass them back as a fetch hint"
```

---

### Task 9: `GraphAdapter.fetch_media` with bounded refresh

The heart of the design: download from cached URLs, and silently re-list when Meta's CDN has expired them.

**Files:**
- Modify: `api/app/ig/graph.py`
- Test: `api/tests/test_graph_adapter.py`

**Interfaces:**
- Consumes: `_get`, `fetch_page`, `_fetcher` from Tasks 6 and 7; `MediaHint` from Task 1.
- Produces: `.fetch_media(shortcode, dest_dir, hint=None) -> list[t.SavedFile]` and `.download_to(url, dest) -> t.SavedFile`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_graph_adapter.py`:

```python
class Fetcher:
    """Serves bytes per URL; any URL not listed is treated as expired."""

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
    """The cached URL 403s; a re-listing supplies a working one."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -k "media or download_to" -v`
Expected: FAIL with `AttributeError: 'GraphAdapter' object has no attribute 'fetch_media'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/app/ig/graph.py`:

```python
from pathlib import Path

from app import paths

_STALE_STATUSES = {403, 404, 410}


class _Stale(Exception):
    """A cached CDN url has expired. Internal to this module."""
```

And the methods on `GraphAdapter`:

```python
    def fetch_media(
        self, shortcode: str, dest_dir: Path, hint: t.MediaHint | None = None
    ) -> list[t.SavedFile]:
        sources = tuple(hint.sources) if hint else ()
        if not sources:
            sources = self._refresh(shortcode, hint)
        try:
            return self._download_all(sources, dest_dir)
        except _Stale:
            # Meta's CDN urls expire. Shallow indexing makes a bounded
            # re-listing cheap, so this is recoverable rather than fatal.
            return self._download_all(self._refresh(shortcode, hint), dest_dir)

    def download_to(self, url: str, dest: Path) -> t.SavedFile:
        try:
            return self._download(t.MediaSource(0, url, "image/jpeg", False), dest)
        except _Stale as exc:
            raise t.IgTransient(f"could not download {dest.name}") from exc

    # ---- internals -----------------------------------------------------
    def _refresh(self, shortcode: str, hint: t.MediaHint | None) -> tuple[t.MediaSource, ...]:
        if hint is None or not hint.username:
            raise t.IgNotFound(
                f"{shortcode} has no owning profile recorded; re-sync it before opening"
            )
        cursor: str | None = None
        for _ in range(max(1, self._settings.graph_refresh_pages)):
            page = self.fetch_page(hint.username, cursor, self._settings.page_size)
            for post in page.posts:
                if post.shortcode == shortcode:
                    return post.sources
            cursor = page.next_cursor
            if cursor is None:
                break
        raise t.IgNotFound(
            f"{shortcode} is too far back to refresh; re-sync {hint.username} to open it"
        )

    def _download_all(
        self, sources: tuple[t.MediaSource, ...], dest_dir: Path
    ) -> list[t.SavedFile]:
        saved = []
        for source in sources:
            ext = "mp4" if source.is_video else "jpg"
            dest = dest_dir / paths.full_filename(source.child_idx, ext)
            saved.append(self._download(source, dest))
        return saved

    def _download(self, source: t.MediaSource, dest: Path) -> t.SavedFile:
        try:
            status, payload = self._fetcher(source.url)
        except Exception as exc:
            raise t.IgTransient(redact(str(exc), self._settings.graph_token)) from exc
        if status in _STALE_STATUSES:
            raise _Stale(source.url)
        if status >= 400 or not payload:
            raise t.IgTransient(f"CDN returned {status}")
        size = paths.atomic_write(dest, lambda fh: fh.write(payload))
        return t.SavedFile(
            child_idx=source.child_idx,
            path=dest,
            mime=source.mime,
            bytes=size,
            width=None,
            height=None,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/graph.py api/tests/test_graph_adapter.py
git commit -m "feat(api): fetch full media with a bounded refresh for expired urls"
```

---

### Task 10: Configuration and the adapter factory

Adds the `IG_GRAPH_*` settings and moves `make_adapter` out of the module Task 11 deletes.

**Files:**
- Create: `api/app/ig/factory.py`
- Modify: `api/app/config.py` (the `adapter` default only — the `graph_*` fields landed in Task 6)
- Modify: `api/app/main.py:9`
- Test: `api/tests/test_graph_adapter.py`, `api/tests/test_ig_contract.py:88`

**Interfaces:**
- Consumes: `GraphAdapter` from Tasks 6–9, `Settings.graph_*` from Task 6.
- Produces: `app.ig.factory.make_adapter(settings)`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_graph_adapter.py`:

```python
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
```

Append to `api/tests/test_ig_contract.py` — the spec requires the protocol be asserted against the real adapter, not only the fake:

```python
def test_graph_adapter_satisfies_the_port(settings):
    """Every method the worker calls must exist with the right arity."""
    import inspect
    from dataclasses import replace

    from app.ig.graph import GraphAdapter

    adapter = GraphAdapter(replace(settings, adapter="graph", graph_version="v99.0"))

    for name in ("fetch_profile", "fetch_page", "fetch_media", "download_to", "login"):
        assert callable(getattr(adapter, name)), f"GraphAdapter is missing {name}"

    assert isinstance(adapter, t.IgAdapter)

    # The hint is optional, so existing call sites keep working.
    hint_param = inspect.signature(adapter.fetch_media).parameters["hint"]
    assert hint_param.default is None
```

`t.IgAdapter` is a `Protocol`; add `@runtime_checkable` to it in `api/app/ig/types.py` so `isinstance` works:

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class IgAdapter(Protocol):
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_graph_adapter.py -k "factory or environment" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ig.factory'`

- [ ] **Step 3: Write minimal implementation**

In `api/app/config.py`, change the adapter default — `"real"` no longer names anything:

```python
        adapter=os.environ.get("IG_ADAPTER", "graph"),
```

In `api/app/ig/types.py`, make the protocol runtime-checkable:

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class IgAdapter(Protocol):
```

Create `api/app/ig/factory.py`:

```python
"""Chooses the adapter. Kept out of any adapter module so that deleting an
implementation never takes the factory with it."""

from app.config import Settings


def make_adapter(settings: Settings):
    if settings.adapter == "fake":
        # Test-only. The e2e stack runs a live server against the seeded
        # dataset, so this must return the same data the seed script wrote.
        from app.ig.fake import seeded_adapter

        return seeded_adapter()

    from app.ig.graph import GraphAdapter

    return GraphAdapter(settings)
```

In `api/app/main.py`, change the import:

```python
from app.ig.factory import make_adapter
```

In `api/tests/test_ig_contract.py`, update `test_seeded_adapter_is_shared_by_make_adapter` to import from the new home:

```python
    from app.ig.factory import make_adapter
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS, whole suite green.

- [ ] **Step 5: Commit**

```bash
git add api/app/config.py api/app/ig/factory.py api/app/ig/types.py api/app/main.py api/tests/test_ig_contract.py api/tests/test_graph_adapter.py
git commit -m "feat(api): default to the Graph adapter and relocate the adapter factory"
```

---

### Task 11: Remove Instaloader

The sweep. Everything Instaloader touched, including the pieces outside `app/ig/`.

**Files:**
- Delete: `api/app/ig/adapter.py`, `api/app/ig/rate.py`, `api/app/ig/login.py`
- Delete: `api/tests/test_adapter_parse.py`, `api/tests/test_anonymous_mode.py`, `api/tests/test_login_entrypoint.py`
- Modify: `api/tests/test_ig_contract.py` (drop `test_only_adapter_module_imports_instaloader`)
- Modify: `api/tests/test_backoff_respect.py`
- Modify: `api/app/config.py`, `api/tests/conftest.py`
- Modify: `api/requirements.txt`, `.env.example`, `docker-compose.yml`

**Interfaces:**
- Consumes: `app.ig.factory.make_adapter` from Task 10.
- Produces: a codebase with no Instaloader import and no credential-based configuration.

- [ ] **Step 1: Write the failing test**

Replace `test_only_adapter_module_imports_instaloader` in `api/tests/test_ig_contract.py` with its successor:

```python
def test_no_module_imports_instaloader():
    """Global constraint: the dependency is gone, not merely unused."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "instaloader" in p.read_text()
    ]
    assert offenders == []


def test_credential_settings_are_gone():
    from app.config import Settings

    fields = set(Settings.__dataclass_fields__)
    assert not fields & {"ig_username", "ig_password", "session_dir", "anonymous", "max_sleep"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_ig_contract.py -k "instaloader or credential" -v`
Expected: FAIL — `app/ig/adapter.py` and `app/ig/rate.py` still import Instaloader, and `Settings` still carries the credential fields.

- [ ] **Step 3: Write minimal implementation**

Delete the source and its tests:

```bash
git rm api/app/ig/adapter.py api/app/ig/rate.py api/app/ig/login.py
git rm api/tests/test_adapter_parse.py api/tests/test_anonymous_mode.py api/tests/test_login_entrypoint.py
```

In `api/app/config.py`, remove these five fields from `Settings` and their five lines from `load_settings()`: `ig_username`, `ig_password`, `session_dir`, `anonymous`, `max_sleep`. Delete the whole anonymous-mode block, including this comment and the `anonymous = ...` line it explains:

```python
    # No credentials means anonymous rather than broken: the app still runs and
    # reports what Instagram says. IG_ANONYMOUS forces it even when set.
```

In `api/tests/conftest.py`, remove the same five arguments from the `Settings(...)` construction, and drop `settings.session_dir` from the `conn` fixture's `mkdir` loop:

```python
    for d in (settings.media_dir, settings.out_dir):
```

In `api/tests/test_backoff_respect.py`, retarget it: the subject is the breaker honouring `retry_after`, which still matters. Replace any Instaloader-raised rate limit with one the Graph adapter produces, keeping the assertion about the breaker unchanged:

```python
def test_breaker_honours_the_wait_meta_asked_for():
    from app.ig import graph, types as t

    headers = {"x-business-use-case-usage": '{"1":[{"estimated_time_to_regain_access":3}]}'}
    exc = graph.classify(400, {"error": {"code": 4, "message": "throttled"}}, headers)

    assert isinstance(exc, t.IgRateLimited)
    assert exc.retry_after == 180.0
```

Keep whatever existing assertions in that file cover the breaker itself; only the source of the `IgRateLimited` changes.

In `api/requirements.txt`, delete the line:

```
instaloader==4.14.1
```

In `.env.example`, delete the `IG_USERNAME`, `IG_PASSWORD`, `IG_ANONYMOUS` and `IG_MAX_SLEEP` blocks with their comments, and add:

```
# Meta Graph API credentials. See docs/superpowers/specs/2026-08-24-instagram-graph-api-design.md
# for the one-time account setup these come from.
IG_GRAPH_TOKEN=
IG_GRAPH_USER_ID=

# Pinned Graph API version, e.g. v23.0. Required: never defaulted in code, so
# that a Meta deprecation is a config change rather than a release.
IG_GRAPH_VERSION=

# How many pages deep to re-list when a cached media url has expired.
IG_GRAPH_REFRESH_PAGES=2

# Percentage of Meta's app-usage allowance at which to stop spending calls.
IG_GRAPH_USAGE_LIMIT=90
```

Change the adapter line in the same file:

```
# graph | fake  -- "fake" runs with no network and is used by the e2e suite.
IG_ADAPTER=graph
```

In `docker-compose.yml`, delete the `SESSION_DIR: /data/session` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS

Then confirm the dependency is genuinely gone from a clean environment:

Run: `cd api && pip uninstall -y instaloader && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A api/ .env.example docker-compose.yml
git commit -m "refactor(api): remove Instaloader and its credential configuration"
```

---

### Task 12: Fixture capture, live canary, and docs

Closes the loop: a way to record real responses, an opt-in check that Meta still behaves, and the setup instructions the operator needs.

**Files:**
- Create: `api/scripts/capture_graph_fixtures.py`
- Rewrite: `api/tests/test_live_canary.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `GraphAdapter`, `load_settings`.
- Produces: a redacting capture script and a network-gated canary.

- [ ] **Step 1: Write the failing test**

Rewrite `api/tests/test_live_canary.py` entirely:

```python
"""Opt-in probe that Meta still answers the way the fixtures claim.

Skipped unless IG_GRAPH_TOKEN is set, so the default suite never touches
the network. Asserts shape, never content: a canary that fails because an
account posted something new is a canary nobody trusts.
"""

import os

import pytest

from app.config import load_settings
from app.ig import types as t
from app.ig.graph import GraphAdapter

pytestmark = pytest.mark.skipif(
    not os.environ.get("IG_GRAPH_TOKEN"),
    reason="IG_GRAPH_TOKEN not set; live canary is opt-in",
)

TARGET = os.environ.get("IG_CANARY_TARGET", "nike")


@pytest.fixture
def adapter():
    return GraphAdapter(load_settings())


def test_token_is_accepted(adapter):
    adapter.login()


def test_profile_has_the_shape_we_map(adapter):
    profile = adapter.fetch_profile(TARGET)
    assert profile.username.lower() == TARGET.lower()
    assert profile.user_id
    assert profile.post_count >= 0
    assert profile.avatar_url.startswith("https://")
    assert profile.is_private is False


def test_first_page_yields_posts_with_sources(adapter):
    page = adapter.fetch_page(TARGET, None, 3)
    assert page.posts, "a public business account should have posts"
    for post in page.posts:
        assert post.shortcode
        assert post.ig_url.startswith("https://")
        assert post.thumb_url.startswith("https://")
        assert post.sources, "every post must carry at least one downloadable source"
        assert post.kind in {"image", "video", "reel", "carousel"}


def test_a_personal_account_is_reported_as_out_of_scope(adapter):
    """Pins the one error mapping the spec left unconfirmed.

    Set IG_CANARY_PERSONAL to a known public *personal* account. If this
    fails, read the message it reports and correct the hint lists in
    app/ig/graph.py rather than loosening this assertion.
    """
    personal = os.environ.get("IG_CANARY_PERSONAL")
    if not personal:
        pytest.skip("IG_CANARY_PERSONAL not set")
    with pytest.raises((t.IgPrivate, t.IgNotFound)) as caught:
        adapter.fetch_profile(personal)
    assert isinstance(caught.value, t.IgPrivate), (
        f"expected IgPrivate for a personal account, got {type(caught.value).__name__}: "
        f"{caught.value}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_live_canary.py -v`
Expected: SKIPPED (all tests), because `IG_GRAPH_TOKEN` is unset. That skip is the pass condition for the default suite.

With a real token configured, run it again: `IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py -v`. Any failure here is real information — fix the mapping, not the test.

- [ ] **Step 3: Write minimal implementation**

Create `api/scripts/capture_graph_fixtures.py`:

```python
"""Record real Business Discovery responses as test fixtures.

Run once, with a live token, to refresh tests/fixtures/graph/. Redacts the
token, our own node id, and fbtrace_id before writing: these files are
committed.

    python scripts/capture_graph_fixtures.py nike
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402
from app.ig.graph import GraphAdapter, _MEDIA_FIELDS, _PROFILE_FIELDS  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "graph"


def redact(payload: dict, settings) -> dict:
    text = json.dumps(payload)
    if settings.graph_token:
        text = text.replace(settings.graph_token, "REDACTED")
    if settings.graph_user_id:
        text = text.replace(settings.graph_user_id, "SELF")
    scrubbed = json.loads(text)
    scrubbed.pop("fbtrace_id", None)
    return scrubbed


def main(target: str) -> int:
    settings = load_settings()
    if not settings.graph_token:
        print("IG_GRAPH_TOKEN must be set to capture fixtures.")
        return 1

    adapter = GraphAdapter(settings)
    OUT.mkdir(parents=True, exist_ok=True)

    profile = adapter._get(f"business_discovery.username({target}){{{_PROFILE_FIELDS}}}")
    (OUT / "profile.json").write_text(json.dumps(redact(profile, settings), indent=2))

    media = adapter._get(
        f"business_discovery.username({target})"
        f"{{media.limit(6){{{_MEDIA_FIELDS}}}}}"
    )
    (OUT / "media_page.json").write_text(json.dumps(redact(media, settings), indent=2))

    print(f"Wrote fixtures for {target} to {OUT}")
    print("Review both files for anything personal before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "nike"))
```

In `README.md`, replace the Instagram login section with the Graph setup. Find the paragraph that instructs `docker compose run --rm api python -m app.ig.login` and substitute:

```markdown
## Instagram access

This tool reads public **Business** and **Creator** accounts through Meta's
Business Discovery API. Personal accounts are not visible to it, and no
workaround exists — that is a property of the API, not a missing feature.

Business Discovery reads other accounts through an account of your own, so
there is a one-time setup:

1. Convert an Instagram account to Business or Creator.
2. Create or choose a Facebook Page and link the Instagram account to it.
3. Create a Meta developer app at developers.facebook.com and add the
   Instagram product.
4. Grant the token `instagram_basic`, `pages_show_list`,
   `pages_read_engagement` and `business_management`.
5. Find your Instagram user id: `GET /me/accounts` for the Page id, then
   `GET /{page-id}?fields=instagram_business_account`.
6. Prefer a Business Manager system-user token, which does not expire, over
   a long-lived user token, which expires after 60 days.

Put the token, the user id and a pinned API version into `.env` as
`IG_GRAPH_TOKEN`, `IG_GRAPH_USER_ID` and `IG_GRAPH_VERSION`.

Verify the setup without starting the stack:

```bash
cd api && IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py -v
```
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS, with the live canary skipped.

Run the full e2e suite to confirm the fake path is untouched:

Run: `cd web && npm run e2e`
Expected: all 8 spec files pass.

- [ ] **Step 5: Commit**

```bash
git add api/scripts/capture_graph_fixtures.py api/tests/test_live_canary.py README.md
git commit -m "feat(api): add fixture capture, a live canary, and Graph setup docs"
```

---

## Verification

After Task 12, confirm the spec's success criteria:

1. `cd api && python -m pytest tests/ -q` — green, no network.
2. `cd web && npm run e2e` — green, fake adapter.
3. `cd api && IG_GRAPH_TOKEN=... python -m pytest tests/test_live_canary.py -v` — green against real Meta.
4. `docker compose up`, add a real public Business account in the UI, confirm thumbnails render and a lightbox open downloads full quality.
5. `grep -ri instaloader api/ .env.example docker-compose.yml` — no matches.
6. `grep -r "$IG_GRAPH_TOKEN" api/tests/fixtures/` — no matches.
