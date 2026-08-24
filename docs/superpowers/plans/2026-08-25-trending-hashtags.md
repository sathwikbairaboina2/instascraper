# Trending Hashtags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank hashtags parsed from cached captions by the engagement of the posts carrying them, over a 24-hour and a 7-day window, and show them as a feed that can hand posts to the existing recreate queue.

**Architecture:** A pure extraction-and-ranking module (`app/services/hashtags.py`) is fed by a window-bounded `SELECT` over `media_items`. Two read-only endpoints expose it. The web app adds one page (`/trending`) that pages the ranking with Load more and, on expanding a row, lists that tag's posts and marks them through the recreate API that already exists.

**Tech Stack:** FastAPI + SQLite (WAL, `sqlite3.Row`), pytest with `TestClient`; Next.js 15 App Router + antd 6, Playwright 1.50.

**Spec:** `docs/superpowers/specs/2026-08-25-trending-hashtags-design.md`

## Global Constraints

- Windows are exactly two: `day` = 24 hours, `week` = 7 days. An unrecognised window is HTTP 400, never a silent default.
- `score = likes + comments + views`, `NULL` counted as zero. Order: `score DESC, post_count DESC, tag ASC`.
- Tags are returned **without** the leading `#`, case-folded, deduped per post.
- Paging follows the existing convention: `limit` / `offset` query params, `total` in the body.
- `taken_at` is compared as a string. Every writer (`graph_map`, the fake adapter) emits ISO-8601 UTC with a `+00:00` offset, so lexicographic order is chronological order. Anything that writes a different offset breaks this, which is why Task 1 pins it with a test.
- No new dependency, backend or frontend.
- Run backend tests from `api/` with `../.venv/Scripts/python.exe -m pytest`. Run e2e from the repo root with `bash scripts/e2e-native.sh`.
- Both full suites must pass before the final commit — not only the new tests.

---

### Task 1: Hashtag extraction and ranking

Pure functions over strings and rows. No database, no FastAPI, so every rule in the spec is testable in isolation.

**Files:**
- Create: `api/app/services/hashtags.py`
- Test: `api/tests/test_hashtags.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `extract_tags(caption: str | None) -> list[str]` — case-folded, deduped, order of first appearance.
  - `WINDOWS: dict[str, timedelta]` — keys `"day"`, `"week"`.
  - `window_since(window: str, now: datetime | None = None) -> str` — ISO-8601 UTC cutoff; raises `ValueError` on an unknown window.
  - `rank(rows: Iterable[Mapping]) -> list[dict]` — each row needs `caption`, `like_count`, `comments_count`, `view_count`. Returns dicts with keys `tag`, `score`, `like_count`, `comments_count`, `view_count`, `post_count`, sorted.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_hashtags.py
"""The rules from the spec, one test each.

Extraction is where this feature is most likely to be quietly wrong: a
regex that also matches a url fragment produces a ranking that looks
plausible and is not.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import hashtags


def test_extracts_tags_in_order():
    assert hashtags.extract_tags("morning run #nike #justdoit") == ["nike", "justdoit"]


def test_folds_case_so_one_tag_is_one_row():
    assert hashtags.extract_tags("#Nike #NIKE #nike") == ["nike"]


def test_counts_a_repeated_tag_once():
    assert hashtags.extract_tags("#sale #sale #sale") == ["sale"]


def test_trailing_punctuation_is_not_part_of_the_tag():
    assert hashtags.extract_tags("#nike, #run. #fit!") == ["nike", "run", "fit"]


def test_keeps_non_ascii_tags():
    assert hashtags.extract_tags("#नाइकी #κόσμος") == ["नाइकी", "κόσμος"]


def test_ignores_a_hash_inside_a_word_or_url():
    assert hashtags.extract_tags("see example.com/#anchor or C#") == []


def test_ignores_a_bare_hash():
    assert hashtags.extract_tags("# #, #") == []


def test_a_newline_separates_tags():
    assert hashtags.extract_tags("caption\n#nike\n#run") == ["nike", "run"]


@pytest.mark.parametrize("caption", [None, "", "no tags here"])
def test_captions_without_tags_yield_nothing(caption):
    assert hashtags.extract_tags(caption) == []


def test_window_since_subtracts_the_right_span():
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    assert hashtags.window_since("day", now) == "2026-08-24T12:00:00+00:00"
    assert hashtags.window_since("week", now) == "2026-08-18T12:00:00+00:00"


def test_window_since_rejects_anything_else():
    with pytest.raises(ValueError):
        hashtags.window_since("month")


def test_since_is_utc_with_a_plus_offset():
    # The endpoint compares this against taken_at as a string, so the format
    # has to match what the writers emit. A 'Z' suffix sorts before '+00:00'
    # and would silently exclude posts.
    assert hashtags.window_since("day").endswith("+00:00")


def _row(caption, likes=None, comments=None, views=None):
    return {
        "caption": caption,
        "like_count": likes,
        "comments_count": comments,
        "view_count": views,
    }


def test_rank_sums_engagement_across_posts():
    items = hashtags.rank([
        _row("#nike", likes=10, comments=2, views=None),
        _row("#nike", likes=5, comments=1, views=100),
    ])
    assert items == [{
        "tag": "nike",
        "score": 118,
        "like_count": 15,
        "comments_count": 3,
        "view_count": 100,
        "post_count": 2,
    }]


def test_rank_treats_missing_engagement_as_zero():
    items = hashtags.rank([_row("#nike")])
    assert items[0]["score"] == 0
    assert items[0]["post_count"] == 1


def test_rank_orders_by_score_then_posts_then_tag():
    items = hashtags.rank([
        _row("#low", likes=1),
        _row("#high", likes=100),
        _row("#tie #alpha", likes=50),
        _row("#tie", likes=0),
    ])
    # #tie: 50 over two posts. #alpha: 50 over one. Same score, more posts wins.
    assert [i["tag"] for i in items] == ["high", "tie", "alpha", "low"]


def test_rank_breaks_a_full_tie_alphabetically():
    items = hashtags.rank([_row("#beta #alpha", likes=7)])
    assert [i["tag"] for i in items] == ["alpha", "beta"]


def test_rank_ignores_posts_with_no_tags():
    assert hashtags.rank([_row("nothing here", likes=999)]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_hashtags.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hashtags'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/services/hashtags.py
"""Hashtags read out of captions, and ranked by how well their posts did.

Nothing is stored. The window in front of every query bounds the scan to
recent posts, which is a small slice of media_items however large that
table gets. If that ever stops being true, these functions are pure enough
that a materialised index can be swapped in underneath them.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone

# A '#' counts at the start of the caption or after whitespace, and nowhere
# else. Without that guard, 'example.com/#anchor' becomes a trending tag.
# \w is unicode-aware for str patterns, which is what keeps non-Latin tags --
# a large share of real Instagram -- from being silently dropped.
_TAG = re.compile(r"(?:^|\s)#(\w+)")

WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
}


def extract_tags(caption: str | None) -> list[str]:
    """Every distinct tag in one caption, case-folded, first-seen order.

    Deduped per post on purpose: a caption repeating '#sale' three times
    should not outrank a post people actually engaged with.
    """
    if not caption:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _TAG.finditer(caption):
        tag = match.group(1).casefold()
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def window_since(window: str, now: datetime | None = None) -> str:
    """The cutoff for a window, as an ISO string comparable to taken_at."""
    delta = WINDOWS.get(window)
    if delta is None:
        raise ValueError(f"unknown window: {window}")
    moment = now or datetime.now(timezone.utc)
    return (moment - delta).isoformat()


def rank(rows: Iterable[Mapping]) -> list[dict]:
    """Aggregate rows into a ranked list of tags.

    The sort has three keys because paging is offset-based: without a total
    order, two rows that compare equal can swap between requests and make a
    page repeat an entry or drop one.
    """
    totals: dict[str, dict] = {}

    for row in rows:
        tags = extract_tags(row["caption"])
        if not tags:
            continue
        likes = row["like_count"] or 0
        comments = row["comments_count"] or 0
        views = row["view_count"] or 0
        for tag in tags:
            entry = totals.get(tag)
            if entry is None:
                entry = totals[tag] = {
                    "tag": tag,
                    "score": 0,
                    "like_count": 0,
                    "comments_count": 0,
                    "view_count": 0,
                    "post_count": 0,
                }
            entry["like_count"] += likes
            entry["comments_count"] += comments
            entry["view_count"] += views
            entry["score"] += likes + comments + views
            entry["post_count"] += 1

    return sorted(
        totals.values(),
        key=lambda i: (-i["score"], -i["post_count"], i["tag"]),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_hashtags.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/hashtags.py api/tests/test_hashtags.py
git commit -m "feat(api): read hashtags out of captions and rank them by engagement"
```

---

### Task 2: Share the media row serializer

`_media_summary` lives in `routes/profiles.py` and Task 4 needs the identical shape. Importing a private name across route modules is the wrong fix; moving it into a service both modules import is the right one, and it is a two-file change.

**Files:**
- Create: `api/app/services/media_view.py`
- Modify: `api/app/routes/profiles.py` (delete `_video_children` and `_media_summary`, import instead)
- Test: `api/tests/test_api_profiles.py` (already covers this — it must keep passing unchanged)

**Interfaces:**
- Consumes: nothing.
- Produces: `media_summary(row) -> dict` and `video_children(row) -> list[int]` in `app.services.media_view`.

- [ ] **Step 1: Create the module by moving the two functions verbatim**

```python
# api/app/services/media_view.py
"""One post, in the shape the media grid consumes.

Lived in routes/profiles.py until a second route needed the same rows. Two
serializers for one grid drift, and the drift shows up as a field the UI
silently reads as undefined.
"""

import json


def video_children(row) -> list[int]:
    """Which slides of a carousel are video.

    `is_video` describes the post, and a carousel is never one even when it
    holds a video slide. Without this the viewer has no way to tell which
    child to render as video, so it renders every slide as an image and the
    video ones break.
    """
    try:
        entries = json.loads(row["src_urls"] or "[]")
    except (TypeError, ValueError):
        return []
    return [int(e["child_idx"]) for e in entries if e.get("is_video")]


def media_summary(row) -> dict:
    return {
        "shortcode": row["shortcode"],
        "kind": row["kind"],
        "taken_at": row["taken_at"],
        "caption": row["caption"],
        "is_video": bool(row["is_video"]),
        "video_children": video_children(row),
        "child_count": row["child_count"],
        "like_count": row["like_count"],
        "comments_count": row["comments_count"],
        "view_count": row["view_count"],
        "full_status": row["full_status"],
        "full_error": row["full_error"],
        "thumb_url": f"/api/media/{row['shortcode']}/thumb",
        "ig_url": row["ig_url"],
    }
```

- [ ] **Step 2: Point `routes/profiles.py` at it**

Delete the `_video_children` and `_media_summary` definitions (currently `api/app/routes/profiles.py:32-60`), add the import beside the existing ones, and rename the one call site.

```python
from app.services.media_view import media_summary
```

```python
        "items": [media_summary(r) for r in rows],
```

Leave the now-unused `import json` in `profiles.py` only if something else in the file still uses it — check with `grep -n "json\." api/app/routes/profiles.py` and remove the import if there are no hits.

- [ ] **Step 3: Run the profile tests to verify nothing moved**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_profiles.py -v`
Expected: PASS, unchanged — these tests never referenced the private names, only the response body.

- [ ] **Step 4: Commit**

```bash
git add api/app/services/media_view.py api/app/routes/profiles.py
git commit -m "refactor(api): move the media row serializer into a service"
```

---

### Task 3: The trending endpoint

**Files:**
- Create: `api/app/routes/hashtags.py`
- Modify: `api/app/main.py` (import and register the router)
- Test: `api/tests/test_api_hashtags.py`

**Interfaces:**
- Consumes: `hashtags.rank`, `hashtags.window_since`, `hashtags.WINDOWS` from Task 1.
- Produces: `GET /api/hashtags/trending` returning `{window, since, total, items}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_api_hashtags.py
"""The trending feed, over the http surface.

Rows are inserted directly rather than driven through the fake adapter:
these tests are about the window and the ranking, and hand-written rows say
exactly what date and engagement each post has.
"""
from datetime import datetime, timedelta, timezone


def _insert(conn, shortcode, caption, hours_ago, likes=0, comments=0, views=None):
    taken = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn.execute(
        "INSERT INTO profiles (username, created_at) VALUES ('nike', ?)"
        " ON CONFLICT(username) DO NOTHING",
        (taken,),
    )
    conn.execute(
        "INSERT INTO media_items"
        " (shortcode, username, kind, taken_at, caption, is_video, child_count,"
        "  like_count, comments_count, view_count, ig_url, discovered_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            shortcode, "nike", "image", taken, caption, 0, 1,
            likes, comments, views,
            f"https://instagram.com/p/{shortcode}/", taken,
        ),
    )


def test_trending_ranks_tags_inside_the_window(client, conn):
    _insert(conn, "a", "#nike #run", hours_ago=2, likes=100, comments=5)
    _insert(conn, "b", "#run", hours_ago=3, likes=10)

    body = client.get("/api/hashtags/trending?window=day").json()

    assert body["window"] == "day"
    assert [i["tag"] for i in body["items"]] == ["run", "nike"]
    assert body["items"][0]["score"] == 115
    assert body["items"][0]["post_count"] == 2


def test_day_window_excludes_a_post_from_last_week(client, conn):
    _insert(conn, "old", "#vintage", hours_ago=48, likes=999)
    _insert(conn, "new", "#fresh", hours_ago=1, likes=1)

    day = client.get("/api/hashtags/trending?window=day").json()
    week = client.get("/api/hashtags/trending?window=week").json()

    assert [i["tag"] for i in day["items"]] == ["fresh"]
    assert [i["tag"] for i in week["items"]] == ["vintage", "fresh"]


def test_a_post_just_inside_the_cutoff_is_counted(client, conn):
    _insert(conn, "edge-in", "#edge", hours_ago=23.9, likes=1)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert [i["tag"] for i in body["items"]] == ["edge"]


def test_a_post_just_outside_the_cutoff_is_not(client, conn):
    _insert(conn, "edge-out", "#edge", hours_ago=24.1, likes=1)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_views_count_towards_the_score(client, conn):
    _insert(conn, "reel", "#reel", hours_ago=1, likes=1, comments=1, views=1000)
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body["items"][0]["score"] == 1002
    assert body["items"][0]["view_count"] == 1000


def test_pages_do_not_overlap_or_skip(client, conn):
    for i in range(10):
        _insert(conn, f"p{i}", f"#tag{i:02d}", hours_ago=1, likes=100 - i)

    first = client.get("/api/hashtags/trending?window=day&limit=4&offset=0").json()
    second = client.get("/api/hashtags/trending?window=day&limit=4&offset=4").json()
    third = client.get("/api/hashtags/trending?window=day&limit=4&offset=8").json()

    assert first["total"] == 10
    assert [len(p["items"]) for p in (first, second, third)] == [4, 4, 2]
    seen = [i["tag"] for p in (first, second, third) for i in p["items"]]
    assert len(set(seen)) == 10, "pages must not repeat a tag"


def test_since_is_reported_so_the_ui_can_say_what_it_covered(client, conn):
    body = client.get("/api/hashtags/trending?window=week").json()
    since = datetime.fromisoformat(body["since"])
    delta = datetime.now(timezone.utc) - since
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)


def test_an_unknown_window_is_a_400(client):
    res = client.get("/api/hashtags/trending?window=month")
    assert res.status_code == 400
    assert "month" in str(res.json()["detail"])


def test_an_empty_window_is_an_empty_list_not_an_error(client):
    body = client.get("/api/hashtags/trending?window=day").json()
    assert body == {"window": "day", "since": body["since"], "total": 0, "items": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_hashtags.py -v`
Expected: FAIL — every request 404s, because the router does not exist.

- [ ] **Step 3: Write the route module**

```python
# api/app/routes/hashtags.py
"""What subjects are doing well right now.

A read-only view over media_items. Nothing here writes, and nothing here
talks to Instagram: the ranking is computed from captions and engagement
that a sync already brought in.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.main_deps import get_conn_dep
from app.services import hashtags

router = APIRouter()


def _since(window: str) -> str:
    """The cutoff, or a 400 naming what was asked for.

    Falling back to a default window would answer a typo with real-looking
    numbers for a period nobody asked about.
    """
    try:
        return hashtags.window_since(window)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unknown window: {window}",
                "allowed": sorted(hashtags.WINDOWS),
            },
        ) from None


@router.get("/hashtags/trending")
def trending(
    window: str = Query("day"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    since = _since(window)
    # taken_at is ISO-8601 UTC with a +00:00 offset from every writer, so a
    # string comparison is a chronological one.
    rows = conn.execute(
        "SELECT caption, like_count, comments_count, view_count"
        " FROM media_items WHERE taken_at >= ?",
        (since,),
    ).fetchall()

    items = hashtags.rank(rows)
    return {
        "window": window,
        "since": since,
        "total": len(items),
        "items": items[offset : offset + limit],
    }
```

- [ ] **Step 4: Register the router in `api/app/main.py`**

Add the import beside the other route imports:

```python
from app.routes import hashtags as hashtag_routes
```

and the registration beside the others, before the health router:

```python
    app.include_router(hashtag_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_hashtags.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/hashtags.py api/app/main.py api/tests/test_api_hashtags.py
git commit -m "feat(api): serve trending hashtags for a day and a week window"
```

---

### Task 4: The posts behind a tag

**Files:**
- Modify: `api/app/routes/hashtags.py`
- Test: `api/tests/test_api_hashtags.py`

**Interfaces:**
- Consumes: `media_summary` from Task 2, `extract_tags` / `window_since` from Task 1.
- Produces: `GET /api/hashtags/{tag}/posts` returning `{tag, window, total, items}` where items are media-grid rows.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_api_hashtags.py`:

```python
def test_tag_posts_returns_only_that_tags_posts(client, conn):
    _insert(conn, "a", "#nike #run", hours_ago=2, likes=1)
    _insert(conn, "b", "#run", hours_ago=3, likes=1)
    _insert(conn, "c", "#other", hours_ago=4, likes=1)

    body = client.get("/api/hashtags/run/posts?window=day").json()

    assert body["tag"] == "run"
    assert body["total"] == 2
    assert {i["shortcode"] for i in body["items"]} == {"a", "b"}


def test_tag_posts_are_newest_first(client, conn):
    _insert(conn, "older", "#run", hours_ago=5)
    _insert(conn, "newer", "#run", hours_ago=1)

    body = client.get("/api/hashtags/run/posts?window=day").json()

    assert [i["shortcode"] for i in body["items"]] == ["newer", "older"]


def test_tag_posts_carry_the_grid_shape(client, conn):
    _insert(conn, "a", "#run", hours_ago=1, likes=7, comments=2)
    item = client.get("/api/hashtags/run/posts?window=day").json()["items"][0]
    assert item["thumb_url"] == "/api/media/a/thumb"
    assert item["like_count"] == 7
    assert item["comments_count"] == 2
    assert item["kind"] == "image"
    assert item["video_children"] == []


def test_tag_posts_match_case_insensitively_and_ignore_a_leading_hash(client, conn):
    _insert(conn, "a", "#Nike", hours_ago=1)
    for path in ("/api/hashtags/nike/posts", "/api/hashtags/%23NIKE/posts"):
        body = client.get(f"{path}?window=day").json()
        assert [i["shortcode"] for i in body["items"]] == ["a"], path


def test_tag_posts_respect_the_window(client, conn):
    _insert(conn, "old", "#run", hours_ago=48)
    assert client.get("/api/hashtags/run/posts?window=day").json()["total"] == 0
    assert client.get("/api/hashtags/run/posts?window=week").json()["total"] == 1


def test_a_tag_nobody_used_is_empty_not_a_404(client):
    res = client.get("/api/hashtags/nothinghere/posts?window=day")
    assert res.status_code == 200
    assert res.json()["total"] == 0
    assert res.json()["items"] == []


def test_tag_posts_page(client, conn):
    for i in range(5):
        _insert(conn, f"p{i}", "#run", hours_ago=i + 1)

    first = client.get("/api/hashtags/run/posts?window=day&limit=2&offset=0").json()
    second = client.get("/api/hashtags/run/posts?window=day&limit=2&offset=2").json()

    assert first["total"] == 5
    assert len(first["items"]) == 2 and len(second["items"]) == 2
    overlap = {i["shortcode"] for i in first["items"]} & {
        i["shortcode"] for i in second["items"]
    }
    assert overlap == set()


def test_tag_posts_reject_an_unknown_window(client):
    assert client.get("/api/hashtags/run/posts?window=year").status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_hashtags.py -k tag_posts -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the route**

In `api/app/routes/hashtags.py`, add the import:

```python
from app.services.media_view import media_summary
```

and the endpoint below `trending`:

```python
@router.get("/hashtags/{tag}/posts")
def tag_posts(
    tag: str,
    window: str = Query("day"),
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn_dep),
):
    """The posts carrying one tag, newest first.

    A tag nobody used is an empty list rather than a 404: a tag that has
    fallen out of the window is not an error, and this endpoint cannot
    honestly tell that case apart from one that never existed.
    """
    since = _since(window)
    wanted = tag.lstrip("#").casefold()

    rows = conn.execute(
        "SELECT * FROM media_items WHERE taken_at >= ?"
        " ORDER BY taken_at DESC, shortcode",
        (since,),
    ).fetchall()
    matched = [r for r in rows if wanted in hashtags.extract_tags(r["caption"])]

    return {
        "tag": wanted,
        "window": window,
        "total": len(matched),
        "items": [media_summary(r) for r in matched[offset : offset + limit]],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_hashtags.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/hashtags.py api/tests/test_api_hashtags.py
git commit -m "feat(api): list the posts behind a trending hashtag"
```

---

### Task 5: A fake dataset this feature can be tested against

The fake adapter writes `caption {i}`, no engagement, and dates pinned to January 2026. Against that, both windows are empty and every e2e assertion would be vacuous.

**Files:**
- Modify: `api/app/ig/fake.py`
- Test: `api/tests/test_fake_dataset.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `FakeAdapter.add_posts(username, count, child_count=1, video=False, tags=(), hours_ago=None, likes=None, comments=None, views=None)`. `seeded_adapter()` keeps its signature and gains recent, tagged, engaged posts.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_fake_dataset.py
"""The canonical fake dataset has to be able to demonstrate the app.

Every e2e assertion about trending is only as meaningful as the data under
it: without recent, tagged, engaged posts, an empty feed and a broken query
look identical.
"""
from datetime import datetime, timedelta, timezone

from app.ig.fake import seeded_adapter
from app.services import hashtags


def _all_posts(adapter):
    return [p for bucket in adapter.posts.values() for p in bucket]


def test_the_seeded_dataset_has_posts_from_the_last_day():
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    recent = [
        p for p in _all_posts(seeded_adapter())
        if datetime.fromisoformat(p.taken_at_iso) >= cutoff
    ]
    assert len(recent) >= 3


def test_the_seeded_dataset_has_posts_older_than_a_day_but_inside_the_week():
    now = datetime.now(timezone.utc)
    mid = [
        p for p in _all_posts(seeded_adapter())
        if now - timedelta(days=7) <= datetime.fromisoformat(p.taken_at_iso)
        < now - timedelta(days=1)
    ]
    assert len(mid) >= 3, "without these, day and week render identically"


def test_seeded_captions_carry_overlapping_hashtags():
    counts: dict[str, int] = {}
    for post in _all_posts(seeded_adapter()):
        for tag in hashtags.extract_tags(post.caption):
            counts[tag] = counts.get(tag, 0) + 1
    assert len(counts) >= 4, "a ranking of one tag proves nothing"
    assert max(counts.values()) >= 2, "a tag must span posts for ranking to matter"


def test_seeded_posts_carry_engagement():
    posts = _all_posts(seeded_adapter())
    assert all(p.like_count is not None for p in posts)
    assert all(p.comments_count is not None for p in posts)
    assert any(p.view_count for p in posts), "reels need views or the score is flat"
    assert all(p.view_count is None for p in posts if not p.is_video), (
        "views exist on reels and nowhere else"
    )


def test_engagement_differs_between_posts():
    likes = {p.like_count for p in _all_posts(seeded_adapter())}
    assert len(likes) > 1, "a flat dataset cannot demonstrate a ranking"


def test_dates_are_stable_within_one_adapter():
    adapter = seeded_adapter()
    first = [p.taken_at_iso for p in _all_posts(adapter)]
    second = [p.taken_at_iso for p in _all_posts(adapter)]
    assert first == second


def test_relative_dates_are_utc_with_a_plus_offset():
    # The endpoint compares taken_at as a string; a 'Z' here would sort
    # wrong against the cutoff and silently drop every seeded post.
    assert all(p.taken_at_iso.endswith("+00:00") for p in _all_posts(seeded_adapter()))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_fake_dataset.py -v`
Expected: FAIL — no recent posts, no tags, no engagement.

- [ ] **Step 3: Extend the fake adapter**

In `api/app/ig/fake.py`, add to the imports:

```python
from datetime import datetime, timedelta, timezone
```

Add a frozen "now" to the dataclass, beside `delay`:

```python
    delay: float = 0.0
    # One instant per adapter, not per call: a test that reads the same post
    # twice must see the same date both times.
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

Replace `add_posts` with:

```python
    def add_posts(
        self,
        username: str,
        count: int,
        child_count: int = 1,
        video: bool = False,
        tags: tuple[str, ...] = (),
        hours_ago: float | None = None,
        likes: int | None = None,
        comments: int | None = None,
        views: int | None = None,
    ):
        """Add posts to a profile's bucket.

        `hours_ago` dates the first post relative to this adapter's start and
        walks an hour further back per post. Left out, posts keep the fixed
        January dates the older tests were written against.
        """
        bucket = self.posts.setdefault(username, [])
        start = len(bucket)
        for i in range(start, start + count):
            shortcode = f"{username}-{i}"
            kind = "carousel" if child_count > 1 else ("reel" if video else "image")
            if hours_ago is None:
                taken = f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00"
            else:
                offset = timedelta(hours=hours_ago + (i - start))
                taken = (self.started_at - offset).isoformat()
            caption = " ".join([f"caption {i}", *(f"#{t}" for t in tags)])
            bucket.append(
                t.IgPost(
                    shortcode=shortcode,
                    kind=kind,
                    taken_at_iso=taken,
                    caption=caption,
                    is_video=video,
                    child_count=child_count,
                    thumb_url=f"https://cdn.test/{shortcode}/thumb.jpg",
                    ig_url=f"https://instagram.com/p/{shortcode}/",
                    # Engagement varies per post so a ranking has something to
                    # order. Views are reels-only, matching Business Discovery.
                    like_count=likes if likes is not None else 100 + i * 37,
                    comments_count=comments if comments is not None else 5 + i * 3,
                    view_count=(views if views is not None else 5000 + i * 911)
                    if video
                    else None,
                )
            )
```

Replace `seeded_adapter` with:

```python
def seeded_adapter() -> FakeAdapter:
    """The canonical fake dataset.

    Shared by scripts/seed_e2e.py and by make_adapter() when IG_ADAPTER=fake,
    so a fake-adapter stack can actually serve the media it seeded. Without a
    single source, the seeded database references posts the running server's
    adapter has never heard of and every media_fetch fails with IgNotFound.

    Dates are relative because the trending feed asks "in the last 24 hours",
    and a dataset pinned to January can only ever answer "nothing".
    """
    adapter = FakeAdapter()
    adapter.add_profile("nike", post_count=8)
    # Today: two tags, overlapping, so the day feed has a ranking to show.
    adapter.add_posts("nike", count=3, tags=("nike", "justdoit"), hours_ago=2)
    adapter.add_posts("nike", count=3, tags=("running",), hours_ago=6)
    # Earlier in the week: present under `week`, absent under `day`, which is
    # what makes the two windows visibly different.
    adapter.add_posts("nike", count=2, child_count=3, tags=("nike", "gear"), hours_ago=72)
    # Two reels: without them the REELS tab has nothing to prove itself on,
    # and views never contribute to a score.
    adapter.add_posts("nike", count=2, video=True, tags=("training",), hours_ago=30)
    return adapter
```

- [ ] **Step 4: Run the new tests, then the whole backend suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_fake_dataset.py -v`
Expected: PASS.

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, every test. The old fixed-date path is preserved for tests that never pass `hours_ago`, so nothing that relied on January should move. If something does fail, fix the fake — do not weaken the assertion that caught it.

- [ ] **Step 5: Commit**

```bash
git add api/app/ig/fake.py api/tests/test_fake_dataset.py
git commit -m "test(api): give the fake dataset hashtags, engagement and recent dates"
```

---

### Task 6: Web API client

**Files:**
- Modify: `web/lib/api.ts`

**Interfaces:**
- Consumes: the endpoints from Tasks 3 and 4.
- Produces:
  - `type TrendWindow = 'day' | 'week'`
  - `type TrendingTag = { tag, score, like_count, comments_count, view_count, post_count }`
  - `type TrendingPage = { window, since, total, items }`
  - `type TagPostsPage = { tag, window, total, items }`
  - `getTrending(window, limit, offset)`, `getTagPosts(tag, window, limit, offset)`

- [ ] **Step 1: Add the types beside the existing ones**

```typescript
export type TrendWindow = 'day' | 'week'

export type TrendingTag = {
  /** Without the leading '#'. The UI adds it. */
  tag: string
  /** likes + comments + views, nulls counted as zero. */
  score: number
  like_count: number
  comments_count: number
  view_count: number
  post_count: number
}

export type TrendingPage = {
  window: TrendWindow
  /** The cutoff the server used, so the page can say what it covered. */
  since: string
  total: number
  items: TrendingTag[]
}

export type TagPostsPage = {
  tag: string
  window: TrendWindow
  total: number
  items: MediaSummary[]
}
```

- [ ] **Step 2: Add the two calls at the end of the file**

```typescript
export const getTrending = (window: TrendWindow, limit = 25, offset = 0) =>
  call<TrendingPage>(`/api/hashtags/trending?window=${window}&limit=${limit}&offset=${offset}`)

export const getTagPosts = (tag: string, window: TrendWindow, limit = 24, offset = 0) =>
  call<TagPostsPage>(
    `/api/hashtags/${encodeURIComponent(tag)}/posts?window=${window}&limit=${limit}&offset=${offset}`,
  )
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(web): call the trending hashtag endpoints"
```

---

### Task 7: The trending page and its nav entry

**Files:**
- Create: `web/app/trending/page.tsx`
- Modify: `web/components/AppShell.tsx` (nav entry + icon import)

**Interfaces:**
- Consumes: `getTrending`, `TrendWindow`, `TrendingTag` from Task 6; `compactCount` from `web/lib/format.ts`.
- Produces: the route `/trending`, and these test ids, which Task 9 asserts on:
  `trending-window`, `trending-row-<tag>`, `trending-score-<tag>`, `trending-posts-<tag>`,
  `trending-load-more`, `trending-empty`, `nav-trending`.

- [ ] **Step 1: Write the page**

Row expansion and marking arrive in Task 8; this task ends with a working, paged, switchable list.

```tsx
// web/app/trending/page.tsx
'use client'

import { Button, Empty, Flex, Layout, Segmented, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import AppShell from '@/components/AppShell'
import { useThemePref } from '@/components/ThemeProvider'
import { getTrending, type TrendWindow, type TrendingTag } from '@/lib/api'
import { compactCount } from '@/lib/format'

const { Content } = Layout
const { Text, Title } = Typography

const PAGE = 25

/** What the day window looks like when nothing was published in it.
 *
 *  Worth spelling out rather than showing a generic "no results": on real
 *  Graph data the cached posts are usually older than a day, and an empty
 *  feed that does not say why is indistinguishable from a broken query.
 */
function EmptyWindow({ window }: { window: TrendWindow }) {
  return (
    <Empty
      data-testid="trending-empty"
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <Text type="secondary">
          {window === 'day'
            ? 'No cached posts were published in the last 24 hours.'
            : 'No cached posts were published in the last 7 days.'}
        </Text>
      }
    />
  )
}

export default function TrendingPage() {
  const { tokens } = useThemePref()
  const [window, setWindow] = useState<TrendWindow>('day')
  const [items, setItems] = useState<TrendingTag[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (next: TrendWindow, offset: number) => {
      setLoading(true)
      try {
        const page = await getTrending(next, PAGE, offset)
        setError(null)
        setTotal(page.total)
        // Replace on a window switch, append on load more. Appending on a
        // switch would show day and week rows in one list.
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    void load(window, 0)
  }, [window, load])

  const more = items.length < total

  return (
    <AppShell>
      <Content style={{ padding: 24, overflowY: 'auto' }}>
        <Flex align="center" justify="space-between" style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0 }}>
            Trending hashtags
          </Title>
          <Segmented
            data-testid="trending-window"
            value={window}
            onChange={(v) => {
              setItems([])
              setTotal(0)
              setWindow(v as TrendWindow)
            }}
            options={[
              { label: 'Day', value: 'day' },
              { label: 'Week', value: 'week' },
            ]}
          />
        </Flex>

        {error && (
          <Text type="danger" data-testid="trending-error">
            {error}
          </Text>
        )}

        {!error && items.length === 0 && !loading && <EmptyWindow window={window} />}

        {items.map((row, i) => (
          <Flex
            key={row.tag}
            data-testid={`trending-row-${row.tag}`}
            align="center"
            gap={12}
            style={{
              padding: '10px 12px',
              borderBottom: `1px solid ${tokens.border}`,
            }}
          >
            <Text type="secondary" style={{ width: 24, textAlign: 'right' }}>
              {i + 1}
            </Text>
            <Text strong style={{ flex: 1 }}>
              #{row.tag}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {row.post_count} {row.post_count === 1 ? 'post' : 'posts'}
            </Text>
            <Text data-testid={`trending-score-${row.tag}`} style={{ width: 72, textAlign: 'right' }}>
              {compactCount(row.score)}
            </Text>
          </Flex>
        ))}

        {more && (
          <Button
            data-testid="trending-load-more"
            block
            loading={loading}
            style={{ marginTop: 16 }}
            onClick={() => void load(window, items.length)}
          >
            Load more
          </Button>
        )}
      </Content>
    </AppShell>
  )
}
```

If `useThemePref()` does not expose a `tokens.border`, read `web/components/ThemeProvider.tsx` and use whichever border token it does expose, or fall back to antd's `theme.useToken()` `token.colorBorderSecondary`, which `AppShell` already uses.

- [ ] **Step 2: Add the nav entry in `AppShell.tsx`**

Add `RiseOutlined` to the `@ant-design/icons` import, and place this `Link` directly above the existing `/recreate` one:

```tsx
            <Link href="/trending">
              <Button
                block
                type="text"
                data-testid="nav-trending"
                icon={<RiseOutlined />}
                style={{ justifyContent: 'flex-start' }}
              >
                Trending
              </Button>
            </Link>
```

- [ ] **Step 3: Typecheck and eyeball it**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

Then start the native e2e stack (`bash scripts/e2e-native.sh --list` seeds and boots without running the suite; or run the stack per the repo's usual dev path) and open `/trending`. Both windows should list tags with scores.

- [ ] **Step 4: Commit**

```bash
git add web/app/trending/page.tsx web/components/AppShell.tsx
git commit -m "feat(web): a trending hashtag feed with day and week windows"
```

---

### Task 8: Expand a tag and mark its posts

**Files:**
- Modify: `web/app/trending/page.tsx`

**Interfaces:**
- Consumes: `getTagPosts` from Task 6, `useRecreateShared()` from `web/components/RecreateProvider` (`{ items, marked, mark }`).
- Produces: test ids `trending-expand-<tag>`, `trending-posts-<tag>`, `trending-post-<shortcode>`, `trending-mark-<tag>`, `trending-marked-<shortcode>`.

- [ ] **Step 1: Add the expansion component**

Add to the imports:

```tsx
import { useRecreateShared } from '@/components/RecreateProvider'
import { getTagPosts, type MediaSummary } from '@/lib/api'
```

Add above `TrendingPage`:

```tsx
/** The posts behind one tag, and a way to send them to the recreate queue.
 *
 *  Selection is local to the expanded row and thrown away when it closes:
 *  it is a scratch list on the way to the queue, and the queue is the thing
 *  that persists.
 */
function TagPosts({ tag, window }: { tag: string; window: TrendWindow }) {
  const { marked, mark } = useRecreateShared()
  const [posts, setPosts] = useState<MediaSummary[] | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    void getTagPosts(tag, window, 24, 0).then((page) => {
      if (live) setPosts(page.items)
    })
    return () => {
      live = false
    }
  }, [tag, window])

  if (posts === null) return <Text type="secondary">Loading…</Text>

  const toggle = (shortcode: string) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(shortcode)) next.delete(shortcode)
      else next.add(shortcode)
      return next
    })

  return (
    <div data-testid={`trending-posts-${tag}`} style={{ padding: '8px 0 12px 36px' }}>
      <Flex wrap gap={8}>
        {posts.map((p) => (
          <button
            key={p.shortcode}
            data-testid={`trending-post-${p.shortcode}`}
            onClick={() => toggle(p.shortcode)}
            style={{
              padding: 0,
              border: picked.has(p.shortcode) ? '2px solid #1677ff' : '2px solid transparent',
              borderRadius: 6,
              background: 'none',
              cursor: 'pointer',
              lineHeight: 0,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={p.thumb_url} alt="" width={72} height={72} style={{ objectFit: 'cover', borderRadius: 4 }} />
            {marked.has(p.shortcode) && (
              <span data-testid={`trending-marked-${p.shortcode}`} style={{ display: 'block', fontSize: 10 }}>
                queued
              </span>
            )}
          </button>
        ))}
      </Flex>
      <Button
        data-testid={`trending-mark-${tag}`}
        size="small"
        type="primary"
        disabled={picked.size === 0 || busy}
        loading={busy}
        style={{ marginTop: 8 }}
        onClick={async () => {
          setBusy(true)
          try {
            await mark([...picked])
            setPicked(new Set())
          } finally {
            setBusy(false)
          }
        }}
      >
        Mark for recreate{picked.size > 0 ? ` (${picked.size})` : ''}
      </Button>
    </div>
  )
}
```

- [ ] **Step 2: Wire expansion into the row**

Add state in `TrendingPage`:

```tsx
  const [open, setOpen] = useState<string | null>(null)
```

Reset it whenever the window changes — inside the `Segmented` `onChange`, alongside `setItems([])`:

```tsx
              setOpen(null)
```

Wrap the row so it can carry its expansion. Replace the `items.map(...)` block's contents with a fragment: the existing `Flex` (now with `onClick`), followed by the expansion when open.

```tsx
        {items.map((row, i) => (
          <div key={row.tag}>
            <Flex
              data-testid={`trending-row-${row.tag}`}
              align="center"
              gap={12}
              onClick={() => setOpen((cur) => (cur === row.tag ? null : row.tag))}
              style={{
                padding: '10px 12px',
                borderBottom: `1px solid ${tokens.border}`,
                cursor: 'pointer',
              }}
            >
              <Text type="secondary" style={{ width: 24, textAlign: 'right' }}>
                {i + 1}
              </Text>
              <Text strong style={{ flex: 1 }} data-testid={`trending-expand-${row.tag}`}>
                #{row.tag}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {row.post_count} {row.post_count === 1 ? 'post' : 'posts'}
              </Text>
              <Text data-testid={`trending-score-${row.tag}`} style={{ width: 72, textAlign: 'right' }}>
                {compactCount(row.score)}
              </Text>
            </Flex>
            {open === row.tag && <TagPosts tag={row.tag} window={window} />}
          </div>
        ))}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/app/trending/page.tsx
git commit -m "feat(web): expand a trending tag and queue its posts for recreation"
```

---

### Task 9: End-to-end coverage, and both suites green

**Files:**
- Create: `web/e2e/trending.spec.ts`

**Interfaces:**
- Consumes: every test id from Tasks 7 and 8, and the seeded dataset from Task 5.

- [ ] **Step 1: Write the spec**

```typescript
// web/e2e/trending.spec.ts
import { expect, test, type Page } from '@playwright/test'

// The recreate queue is server state shared with the other specs, so this
// file leaves it exactly as it found it.
async function clearRecreate(page: Page) {
  const res = await page.request.get('/api/recreate')
  for (const item of (await res.json()).items) {
    await page.request.delete(`/api/recreate/${item.shortcode}`)
  }
}

test.beforeEach(async ({ page }) => {
  await clearRecreate(page)
})

test.afterEach(async ({ page }) => {
  await clearRecreate(page)
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('the nav reaches the feed and the day window has tags', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('nav-trending').click()

  await expect(page).toHaveURL(/\/trending$/)
  await expect(page.getByTestId('trending-row-nike')).toBeVisible()
  await expect(page.getByTestId('trending-score-nike')).not.toBeEmpty()
})

test('switching to the week window brings in older tags', async ({ page }) => {
  await page.goto('/trending')
  // #gear is on posts three days old: absent from the day window by design.
  await expect(page.getByTestId('trending-row-gear')).toHaveCount(0)

  await page.getByTestId('trending-window').getByText('Week').click()

  await expect(page.getByTestId('trending-row-gear')).toBeVisible()
})

test('switching back to day drops the week-only tags again', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-window').getByText('Week').click()
  await expect(page.getByTestId('trending-row-gear')).toBeVisible()

  await page.getByTestId('trending-window').getByText('Day').click()

  await expect(page.getByTestId('trending-row-gear')).toHaveCount(0)
})

test('load more appends a page without repeating rows', async ({ page }) => {
  // Small page size so the seeded dataset is enough to page at all.
  await page.route('**/api/hashtags/trending*', async (route) => {
    const url = new URL(route.request().url())
    url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  })

  await page.goto('/trending')
  await expect(page.getByTestId('trending-load-more')).toBeVisible()
  const first = await page.locator('[data-testid^="trending-row-"]').count()
  expect(first).toBe(1)

  await page.getByTestId('trending-load-more').click()

  const rows = page.locator('[data-testid^="trending-row-"]')
  await expect(rows).toHaveCount(2)
  const ids = await rows.evaluateAll((els) =>
    els.map((e) => e.getAttribute('data-testid')),
  )
  expect(new Set(ids).size).toBe(2)
})

test('expanding a tag lists the posts behind it', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-expand-nike').click()

  await expect(page.getByTestId('trending-posts-nike')).toBeVisible()
  await expect(
    page.getByTestId('trending-posts-nike').locator('[data-testid^="trending-post-"]'),
  ).not.toHaveCount(0)
})

test('a post picked from a tag lands in the recreate queue', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-expand-nike').click()

  const first = page
    .getByTestId('trending-posts-nike')
    .locator('[data-testid^="trending-post-"]')
    .first()
  const shortcode = (await first.getAttribute('data-testid'))!.replace('trending-post-', '')

  await first.click()
  await page.getByTestId('trending-mark-nike').click()

  await expect(page.getByTestId(`trending-marked-${shortcode}`)).toBeVisible()

  await page.goto('/recreate')
  await expect(page.getByTestId(`recreate-row-${shortcode}`)).toBeVisible()
})

test('an empty window says why it is empty', async ({ page }) => {
  await page.route('**/api/hashtags/trending*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        window: 'day',
        since: '2026-08-24T00:00:00+00:00',
        total: 0,
        items: [],
      }),
    }),
  )

  await page.goto('/trending')

  await expect(page.getByTestId('trending-empty')).toContainText('last 24 hours')
})
```

- [ ] **Step 2: Run the new spec**

Run: `bash scripts/e2e-native.sh trending.spec.ts`
Expected: PASS, all seven tests.

If a tag name in the spec does not exist in the seeded data, read what `/api/hashtags/trending?window=week` actually returns and fix the **spec** to match the seed — do not loosen an assertion into one that would pass on an empty feed.

- [ ] **Step 3: Run both suites in full**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — the pre-existing 322 plus the new tests.

Run: `bash scripts/e2e-native.sh`
Expected: PASS — the pre-existing 81 (3 skipped) plus the new 7.

Every failure gets fixed before the commit. A pre-existing test that this branch broke is this branch's problem.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/trending.spec.ts
git commit -m "test(web): cover the trending feed end to end"
```

- [ ] **Step 5: Update the README**

Add a short paragraph under "Everyday use" describing the Trending page: the two windows, that ranking is by likes + comments + views of posts carrying the tag, and that expanding a tag lets its posts be queued for recreation.

```bash
git add README.md
git commit -m "docs: describe the trending hashtag feed"
```

---

## Self-Review

**Spec coverage.** Windows (Tasks 1, 3), extraction rules (Task 1), score and ordering (Tasks 1, 3), both endpoints and their paging and 400s (Tasks 3, 4), the shared serializer the spec's "same shape as the media grid" promise depends on (Task 2), the fake dataset the spec calls out as a prerequisite (Task 5), the page, windows, load more, expansion, marking, and honest empty state (Tasks 6-8), and the full test matrix (Tasks 1, 3, 4, 5, 9).

**Type consistency.** `extract_tags`, `window_since`, `WINDOWS`, `rank` are used in Tasks 3 and 4 exactly as defined in Task 1. `media_summary` is defined in Task 2 and used in Task 4. `getTrending` / `getTagPosts` are defined in Task 6 and used in Tasks 7 and 8. Test ids produced in Tasks 7 and 8 match the ones asserted in Task 9. Tags are without a leading `#` everywhere.

**Known gap, deliberate.** No test pins the browser's rendering of a score above a million, because the seeded engagement does not reach it; `compactCount` already owns that rounding and is unit-tested where it lives.
