# Instagram-Shaped Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the profile page into Instagram's layout with POSTS / REELS / SAVED tabs and Instagram's palette, add a live Meta quota readout to the header, and stop opening profiles with only three posts.

**Architecture:** Backend first, UI second — every interface change lands on data that already works. The Graph adapter starts reporting Meta's `x-app-usage` figure and classifying reels from `media_product_type` instead of a URL guess; the worker's pacer splits so CDN thumbnail downloads stop being throttled like scraped endpoints; then the web app's five-theme system collapses to one Instagram token set and the profile page's filter chips become tabs.

**Tech Stack:** FastAPI + SQLite + httpx (api), Next.js 15 + React 19 + antd 6 (web), pytest (backend), Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-08-24-instagram-profile-ui-design.md`

## Global Constraints

- Python runs through the repo venv: `../.venv/Scripts/python.exe -m pytest` from `api/`.
- Full backend suite: `cd api && ../.venv/Scripts/python.exe -m pytest -q`. Must be green before any commit.
- Full e2e suite: `bash scripts/e2e-native.sh` from the repo root. Runs against the **fake** adapter and an isolated `.e2e/` directory.
- `tests/test_live_canary.py` only runs when `IG_GRAPH_TOKEN` is set. Do not add live network calls to any other test.
- The story gradient `#fcb045 → #fd1d1d → #833ab4` appears on the avatar ring and nowhere else.
- Instagram tokens, exact values: ground `#000000`/`#ffffff`, surface `#121212`/`#fafafa`, hairline `#262626`/`#dbdbdb`, text `#f5f5f5`/`#000000`, text-secondary `#a8a8a8`/`#737373`, action `#0095f6`, destructive `#ed4956`.
- No countdown, estimated reset time, or derived clock in the quota readout. Usage percentage only.
- Commit after every task. Conventional commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`).

---

### Task 1: Classify reels from `media_product_type`

`graph_map.post_from_node` currently infers a reel from `"/reel/" in permalink`. Meta returns `media_product_type` (`FEED` or `REELS`) and we already request it in `_MEDIA_FIELDS` — we just throw it away. The URL shape is a proxy; the field is the definition. The tabs depend on this being right.

**Files:**
- Modify: `api/app/ig/graph_map.py:88-93`
- Modify: `api/tests/fixtures/graph/media_page.json` (add `media_product_type` to each item)
- Test: `api/tests/test_graph_map.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `post_from_node(node: dict) -> t.IgPost` where `kind` is `"reel"` when `node["media_product_type"] == "REELS"`. Values stay `"image" | "video" | "reel" | "carousel"`.

- [ ] **Step 1: Add `media_product_type` to the page fixture**

Open `api/tests/fixtures/graph/media_page.json`. Each object inside `business_discovery.media.data` needs a `media_product_type`. Give the `IMAGE` and `CAROUSEL_ALBUM` items `"FEED"`. Give the `VIDEO` item `"REELS"`. Example of one edited item:

```json
{
  "id": "2",
  "caption": "a video",
  "media_type": "VIDEO",
  "media_product_type": "REELS",
  "media_url": "https://scontent.cdninstagram.com/v2.mp4",
  "thumbnail_url": "https://scontent.cdninstagram.com/t2.jpg",
  "permalink": "https://www.instagram.com/reel/BBBBBBBBBBB/",
  "timestamp": "2026-08-19T10:00:00+0000"
}
```

- [ ] **Step 2: Write the failing tests**

Add to `api/tests/test_graph_map.py`:

```python
def test_reel_is_classified_from_the_product_type_not_the_url():
    """The permalink shape is a proxy; media_product_type is the definition."""
    node = {
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "media_url": "https://cdn/v.mp4",
        "thumbnail_url": "https://cdn/t.jpg",
        # A /p/ permalink on a reel: the old heuristic would miss this.
        "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "reel"


def test_feed_video_is_not_a_reel():
    node = {
        "media_type": "VIDEO",
        "media_product_type": "FEED",
        "media_url": "https://cdn/v.mp4",
        "thumbnail_url": "https://cdn/t.jpg",
        "permalink": "https://www.instagram.com/reel/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "video"


def test_a_missing_product_type_falls_back_to_the_media_type():
    """Older recorded payloads carry no product type; they must still map."""
    node = {
        "media_type": "IMAGE",
        "media_url": "https://cdn/i.jpg",
        "permalink": "https://www.instagram.com/p/AAAAAAAAAAA/",
        "timestamp": "2026-08-20T14:03:11+0000",
    }
    assert graph_map.post_from_node(node).kind == "image"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_map.py -q`
Expected: FAIL — `test_reel_is_classified_from_the_product_type_not_the_url` gets `"video"`, `test_feed_video_is_not_a_reel` gets `"reel"`.

- [ ] **Step 4: Implement**

In `api/app/ig/graph_map.py`, replace the permalink heuristic in `post_from_node`:

```python
def post_from_node(node: dict) -> t.IgPost:
    permalink = node.get("permalink") or ""
    media_type = node.get("media_type", "")
    kind = _KIND.get(media_type, "image")
    # Meta labels the surface a post was published to. A reel can carry a
    # /p/ permalink, so the url shape is only ever a guess at this.
    if kind == "video" and node.get("media_product_type") == "REELS":
        kind = "reel"
    children = _children(node)
    return t.IgPost(
```

The rest of the function is unchanged.

- [ ] **Step 5: Run the full backend suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Watch `test_graph_adapter.py` — the fixture edit touches it too.

- [ ] **Step 6: Commit**

```bash
git add api/app/ig/graph_map.py api/tests/test_graph_map.py api/tests/fixtures/graph/media_page.json
git commit -m "fix(api): classify reels from media_product_type"
```

---

### Task 2: Carry `followers_count` through to the profile

Instagram's header shows a follower count. Business Discovery returns `followers_count` on every profile call and `profile_from_payload` drops it. It needs a column, a mapping, and a place in the API response.

**Files:**
- Modify: `api/app/ig/types.py:39-46` (`IgProfile`)
- Modify: `api/app/ig/graph_map.py:23-34` (`profile_from_payload`)
- Modify: `api/app/schema.sql:1-13` (profiles table)
- Modify: `api/app/db.py:60-70` (migration map)
- Modify: `api/app/worker/handlers.py` (profile upsert)
- Modify: `api/app/routes/profiles.py` (detail response)
- Modify: `api/tests/fixtures/graph/profile.json`
- Test: `api/tests/test_graph_map.py`, `api/tests/test_handlers_profile.py`, `api/tests/test_api_profiles.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `IgProfile.followers_count: int` (defaults to `0`); `profiles.followers_count` column; `GET /api/profiles/{username}` gains `"followers_count": int | None`.

- [ ] **Step 1: Write the failing mapping test**

Add to `api/tests/test_graph_map.py`:

```python
def test_profile_carries_the_follower_count():
    profile = graph_map.profile_from_payload(load("profile.json"))
    assert profile.followers_count == 291399778


def test_a_profile_without_a_follower_count_maps_to_zero():
    payload = {"business_discovery": {"username": "x", "id": "1", "media_count": 0}}
    assert graph_map.profile_from_payload(payload).followers_count == 0
```

Then add `"followers_count": 291399778` to the `business_discovery` object in `api/tests/fixtures/graph/profile.json`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_map.py -q`
Expected: FAIL with `AttributeError: 'IgProfile' object has no attribute 'followers_count'`.

- [ ] **Step 3: Add the field to the type**

In `api/app/ig/types.py`, add to `IgProfile` — **last, with a default**, so `FakeAdapter.add_profile` and every existing construction keep working:

```python
@dataclass(frozen=True)
class IgProfile:
    username: str
    user_id: str
    full_name: str
    biography: str
    is_private: bool
    post_count: int
    avatar_url: str
    # Business Discovery always returns this; the fake adapter and older
    # recorded payloads do not, so it defaults rather than being required.
    followers_count: int = 0
```

- [ ] **Step 4: Map it**

In `api/app/ig/graph_map.py`, inside `profile_from_payload`, add after `post_count`:

```python
        post_count=int(bd.get("media_count") or 0),
        followers_count=int(bd.get("followers_count") or 0),
        avatar_url=bd.get("profile_picture_url") or "",
```

- [ ] **Step 5: Run the mapping tests**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_map.py -q`
Expected: PASS.

- [ ] **Step 6: Add the column and its migration**

In `api/app/schema.sql`, add to the `profiles` table after `post_count`:

```sql
  post_count      INTEGER,
  followers_count INTEGER,
```

In `api/app/db.py`, `_ADDED_COLUMNS` is keyed by table and then by column. `profiles` has no entry yet, so add one:

```python
_ADDED_COLUMNS = {
    "media_items": {
        "src_urls": "ALTER TABLE media_items ADD COLUMN src_urls TEXT",
        "src_urls_at": "ALTER TABLE media_items ADD COLUMN src_urls_at TEXT",
    },
    "profiles": {
        "followers_count": "ALTER TABLE profiles ADD COLUMN followers_count INTEGER",
    },
}
```

`migrate` already walks every table in the map and skips columns that exist, so nothing else changes.

- [ ] **Step 7: Write the failing handler test**

Add to `api/tests/test_handlers_profile.py`:

```python
def test_profile_sync_stores_the_follower_count(ctx):
    ctx.adapter.add_profile("nike", post_count=42)
    ctx.adapter.profiles["nike"] = replace(
        ctx.adapter.profiles["nike"], followers_count=1234
    )

    handlers.handle_profile_sync(ctx, {"username": "nike"})

    row = ctx.conn.execute(
        "SELECT followers_count FROM profiles WHERE username='nike'"
    ).fetchone()
    assert row["followers_count"] == 1234
```

Add `from dataclasses import replace` to the imports at the top of that file.

- [ ] **Step 8: Run it to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_handlers_profile.py -q`
Expected: FAIL — the column is never written.

- [ ] **Step 9: Write it in the upsert**

In `api/app/worker/handlers.py`, find the `INSERT INTO profiles ... ON CONFLICT` statement at the top of `handle_profile_sync`. Add `followers_count` to the column list, add one more `?` to the `VALUES`, add `followers_count=excluded.followers_count` to the `DO UPDATE SET` clause, and pass `profile.followers_count` in the parameter tuple in the same position as the column. Read the statement carefully — the parameter order must match the column order exactly.

- [ ] **Step 10: Expose it on the detail route**

In `api/app/routes/profiles.py`, the profile-detail handler builds a dict around line 86 (the one containing `"exhausted": row["next_cursor"] == ""`). Add:

```python
        "followers_count": row["followers_count"],
```

- [ ] **Step 11: Write the failing API test**

Add to `api/tests/test_api_profiles.py`:

```python
def test_profile_detail_reports_the_follower_count(client, conn):
    conn.execute("UPDATE profiles SET followers_count=99 WHERE username='nike'")

    body = client.get("/api/profiles/nike").json()

    assert body["followers_count"] == 99
```

If that module's fixtures differ, match the existing tests in the file — several already fetch `/api/profiles/nike` and assert on the body.

- [ ] **Step 12: Run the full backend suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add api/app api/tests
git commit -m "feat(api): carry the follower count through to the profile"
```

---

### Task 3: Report Meta's quota usage

The adapter already parses `x-app-usage` but keeps only a running maximum, so the figure climbs for the life of the process and never reflects the hourly reset. That is correct for the backoff guard and wrong for a readout. The adapter keeps both, and `/api/status` exposes the readable one.

**Files:**
- Modify: `api/app/ig/graph.py:129` (`__init__`), `:138` (backoff check), `:157` (usage assignment)
- Modify: `api/app/routes/status.py:12-22`
- Test: `api/tests/test_graph_adapter.py`, `api/tests/test_api_status.py` (create if absent)

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: `GraphAdapter.usage` property returning `float` (latest reported percentage, 0.0 before any call); `GraphAdapter.usage_peak` property returning `float` (high-water mark, what the backoff guard reads). `GET /api/status` gains `"usage": float | None` — `None` when the live adapter reports no usage (the fake adapter).

- [ ] **Step 1: Write the failing adapter tests**

Add to `api/tests/test_graph_adapter.py`:

```python
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
```

Check how `Transport` in that file handles headers — the existing calls pass `(200, {}, body)`, so the middle element is already the header dict.

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_adapter.py -q`
Expected: FAIL with `AttributeError: 'GraphAdapter' object has no attribute 'usage'`.

- [ ] **Step 3: Implement**

In `api/app/ig/graph.py`, change `__init__`:

```python
        self._usage = 0.0
        self._usage_peak = 0.0
```

Add the two properties directly after `__init__`:

```python
    @property
    def usage(self) -> float:
        """Meta's latest reported percentage of the hourly quota."""
        return self._usage

    @property
    def usage_peak(self) -> float:
        """Highest reading seen this process. What the backoff guard trusts."""
        return self._usage_peak
```

Change the backoff guard in `_get` to read the peak:

```python
        if self._usage_peak >= self._settings.graph_usage_limit:
            raise t.IgRateLimited(
                f"app usage at {self._usage_peak:.0f}% of Meta's limit; backing off"
            )
```

And change the assignment after the transport call:

```python
        self._usage = usage_percent(response_headers)
        self._usage_peak = max(self._usage_peak, self._usage)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_graph_adapter.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing status test**

The fake adapter has no `usage` attribute, so the route must not assume one. Add to `api/tests/test_api_status.py` (create the file if it does not exist, copying the fixtures used by `api/tests/test_api_profiles.py`):

```python
def test_status_reports_no_usage_for_an_adapter_that_does_not_track_it(client):
    """The fake adapter never calls Meta; inventing a 0% would read as fact."""
    assert client.get("/api/status").json()["usage"] is None
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_api_status.py -q`
Expected: FAIL with `KeyError: 'usage'`.

- [ ] **Step 7: Implement**

In `api/app/routes/status.py`, inside `get_status`, add before the return:

```python
    # The fake adapter never calls Meta. A 0% there would read as a real
    # measurement rather than an absent one.
    usage = getattr(current.adapter, "usage", None)
```

and add to the returned dict:

```python
        "usage": usage,
```

- [ ] **Step 8: Run the full backend suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add api/app/ig/graph.py api/app/routes/status.py api/tests
git commit -m "feat(api): report Meta's quota usage on the status endpoint"
```

---

### Task 4: Split the pacer and open profiles with twelve posts

A Graph page of 200 costs exactly one call — the same as a page of 3 — so the small first page buys nothing on the quota. What it avoids is thumbnail downloads, and those come from `scontent.cdninstagram.com`, which does not touch `x-app-usage` at all. Pacing them at the Graph interval is scraper-era caution: twelve posts would be thirty-six seconds of deliberate waiting for no benefit.

**Files:**
- Modify: `api/app/config.py:26-43`
- Modify: `api/app/worker/runner.py:19-24` (`HandlerContext`), `:39-45`, `:98`
- Modify: `api/app/worker/handlers.py:119` (thumbnail pacing)
- Modify: `api/app/main.py:50,63`
- Modify: `.env.example`
- Test: `api/tests/test_handlers_profile.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-3.
- Produces: `Settings.cdn_min_interval: float` (default `0.5`); `Settings.first_page_size` default changes `3` → `12`; `HandlerContext.cdn_pacer: Pacer`; `Worker.__init__` gains a `cdn_pacer: Pacer` keyword argument.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_handlers_profile.py`. The `ctx` fixture in that file builds a `HandlerContext` — this test needs a second pacer on it:

```python
def test_thumbnails_are_paced_separately_from_graph_calls(ctx, settings):
    """CDN downloads do not spend Meta's quota, so they do not wait like it."""
    ctx.adapter.add_profile("nike")
    ctx.adapter.add_posts("nike", count=3)
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    ctx.enqueued.clear()

    handlers.handle_page_fetch(ctx, {"username": "nike"})

    # One Graph call for the listing, one CDN fetch per thumbnail.
    assert ctx.pacer.waits == 1
    assert ctx.cdn_pacer.waits == 3
```

Update the `ctx` fixture in the same file to provide counting pacers and the new field:

```python
class CountingPacer:
    """A pacer that records rather than sleeps."""

    def __init__(self):
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


@pytest.fixture
def ctx(settings, conn):
    adapter = FakeAdapter()
    enqueued = []
    context = HandlerContext(
        conn=conn,
        adapter=adapter,
        settings=settings,
        pacer=CountingPacer(),
        cdn_pacer=CountingPacer(),
        enqueue=lambda kind, payload: enqueued.append((kind, payload)),
    )
    context.enqueued = enqueued  # type: ignore[attr-defined]
    return context
```

Other tests in this file assert on `Pacer(min_interval=0.0)` behaviour only incidentally; if any of them break on the swap, they were depending on the real pacer and should take `CountingPacer` too.

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_handlers_profile.py -q`
Expected: FAIL — `HandlerContext` has no `cdn_pacer` field.

- [ ] **Step 3: Add the setting**

In `api/app/config.py`, add to the `Settings` dataclass after `ig_min_interval`:

```python
    ig_min_interval: float
    cdn_min_interval: float
```

and in `load_settings`:

```python
        ig_min_interval=float(os.environ.get("IG_MIN_INTERVAL", "3")),
        # Thumbnails come from Meta's CDN, which does not spend the Graph
        # quota. Pacing them is politeness, not rate-limit avoidance, so the
        # floor is far lower than the one on api calls.
        cdn_min_interval=float(os.environ.get("IG_CDN_MIN_INTERVAL", "0.5")),
```

Change the first-page default in the same function:

```python
        # A Graph page of 200 costs the same single call as a page of 3, so
        # this is bounded by thumbnail fetches, not by quota. Twelve fills
        # the first screen of the grid.
        first_page_size=int(os.environ.get("FIRST_PAGE_SIZE", "12")),
```

Replace the existing comment above `first_page_size` — it explains a cost that no longer exists.

- [ ] **Step 4: Thread the second pacer through**

In `api/app/worker/runner.py`, add to `HandlerContext`:

```python
    pacer: Pacer
    cdn_pacer: Pacer
```

Add `cdn_pacer: Pacer` to `Worker.__init__`'s signature next to `pacer`, assign `self.cdn_pacer = cdn_pacer`, and pass `cdn_pacer=self.cdn_pacer` where the context is built around line 98.

In `api/app/main.py`, create it beside the existing one:

```python
    app.state.pacer = Pacer(min_interval=base.ig_min_interval)
    app.state.cdn_pacer = Pacer(min_interval=base.cdn_min_interval)
```

and pass `app.state.cdn_pacer` to the `Worker` construction around line 50, matching the argument order you gave `Worker.__init__`.

- [ ] **Step 5: Use it for thumbnails**

In `api/app/worker/handlers.py`, in `handle_page_fetch`, change the thumbnail branch:

```python
        thumb_dest = paths.item_dir(ctx.settings.media_dir, username, post.shortcode) / "thumb.jpg"
        if not thumb_dest.exists():
            ctx.cdn_pacer.wait()
            saved = ctx.adapter.download_to(post.thumb_url, thumb_dest)
```

Leave the `ctx.pacer.wait()` before `fetch_page` alone — that one guards a real Graph call.

Check `handle_profile_sync` too: the avatar download at `handlers.py:40` is also a CDN fetch and should use `ctx.cdn_pacer`.

- [ ] **Step 6: Run the tests**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest tests/test_handlers_profile.py -q`
Expected: PASS.

- [ ] **Step 7: Document the new setting**

In `.env.example`, add below the `IG_MIN_INTERVAL` entry:

```
# Seconds enforced between Instagram CDN downloads (thumbnails, avatars).
# These do not spend the Graph API quota, so the floor is much lower than
# IG_MIN_INTERVAL.
IG_CDN_MIN_INTERVAL=0.5
```

Also update the `FIRST_PAGE_SIZE` comment there if it repeats the old reasoning.

- [ ] **Step 8: Run the full backend suite**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. `test_first_page_is_small_and_load_more_takes_a_full_page` asserts on `first_page_size` — it reads the value from settings rather than hardcoding `3`, but check it and fix if it hardcodes.

- [ ] **Step 9: Commit**

```bash
git add api .env.example
git commit -m "feat(api): pace CDN downloads apart from Graph calls"
```

---

### Task 5: Replace the five themes with Instagram's palette

`lib/themes.ts` carries five accent themes. One Instagram token set with dark and light variants replaces them, and the theme Segmented leaves the header.

**Files:**
- Modify: `web/lib/themes.ts` (whole file)
- Modify: `web/components/ThemeProvider.tsx:56-85`
- Modify: `web/components/AppShell.tsx:174-188` (remove the THEME control)
- Test: `bash scripts/e2e-native.sh`

**Interfaces:**
- Consumes: nothing from Tasks 1-4.
- Produces: `web/lib/themes.ts` exports `IG: { dark: Tokens; light: Tokens }`, `GRADIENT: string`, `loadPref(): { dark: boolean }`, `savePref(pref: { dark: boolean }): void`. `Tokens` is `{ ground, surface, hairline, text, textSecondary, action, destructive }`, all `string`. `useThemePref()` returns `{ tokens: Tokens; dark: boolean; setDark: (dark: boolean) => void }` — **`themed` and `setThemeName` are gone**; every consumer must be updated.

- [ ] **Step 1: Rewrite the theme module**

Replace the whole contents of `web/lib/themes.ts`:

```ts
export type Tokens = {
  ground: string
  surface: string
  hairline: string
  text: string
  textSecondary: string
  action: string
  destructive: string
}

/** Instagram's own palette. One set, two modes -- the app follows the thing
 *  it indexes rather than inventing a look of its own. */
export const IG: { dark: Tokens; light: Tokens } = {
  dark: {
    ground: '#000000',
    surface: '#121212',
    hairline: '#262626',
    text: '#f5f5f5',
    textSecondary: '#a8a8a8',
    action: '#0095f6',
    destructive: '#ed4956',
  },
  light: {
    ground: '#ffffff',
    surface: '#fafafa',
    hairline: '#dbdbdb',
    text: '#000000',
    textSecondary: '#737373',
    action: '#0095f6',
    destructive: '#ed4956',
  },
}

/** The story ring, and nothing else. Instagram spends this sparingly and so
 *  do we: on buttons and headers it stops reading as Instagram and starts
 *  reading as an imitation of it. */
export const GRADIENT = 'conic-gradient(from 200deg, #fcb045, #fd1d1d, #833ab4, #fcb045)'

const KEY = 'instascraper:theme'

export type ThemePref = { dark: boolean }

export function loadPref(): ThemePref {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { dark: true }
    return { dark: JSON.parse(raw)?.dark !== false }
  } catch {
    return { dark: true }
  }
}

export function savePref(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, JSON.stringify(pref))
  } catch {
    // private window or blocked storage: the choice just is not remembered
  }
}
```

The old `KEY` stored `{name, dark}`. Reading it back yields a `dark` boolean and ignores the stale `name`, so existing users keep their light/dark choice.

- [ ] **Step 2: Rewrite the provider**

In `web/components/ThemeProvider.tsx`, drop the theme-name state entirely:

```tsx
'use client'

import { ConfigProvider, theme as antdTheme } from 'antd'
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { mono, sans } from '@/lib/fonts'
import { IG, loadPref, savePref, type Tokens } from '@/lib/themes'

type Ctx = {
  tokens: Tokens
  dark: boolean
  setDark: (dark: boolean) => void
}

const ThemeCtx = createContext<Ctx>({
  tokens: IG.dark,
  dark: true,
  setDark: () => {},
})

export const useThemePref = () => useContext(ThemeCtx)

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [dark, setDarkState] = useState(true)

  // Read the stored preference after mount: localStorage does not exist on the
  // server, and reading it during render would desync the first paint.
  useEffect(() => {
    setDarkState(loadPref().dark)
  }, [])

  const tokens = dark ? IG.dark : IG.light

  const value = useMemo<Ctx>(
    () => ({
      tokens,
      dark,
      setDark: (d) => {
        setDarkState(d)
        savePref({ dark: d })
      },
    }),
    [tokens, dark],
  )

  return (
    <ThemeCtx.Provider value={value}>
      <ConfigProvider
        theme={{
          algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: tokens.action,
            colorInfo: tokens.action,
            colorError: tokens.destructive,
            colorTextLightSolid: '#ffffff',
            colorBgBase: tokens.ground,
            colorBorder: tokens.hairline,
            borderRadius: 8,
            fontFamily: sans.style.fontFamily,
            fontFamilyCode: mono.style.fontFamily,
            fontSize: 14,
            controlHeight: 34,
            wireframe: false,
          },
          components: {
            Button: { borderRadius: 8, fontWeight: 600 },
            Input: { borderRadius: 8 },
            Segmented: { borderRadius: 8 },
            Tag: { borderRadiusSM: 6 },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeCtx.Provider>
  )
}
```

Instagram's own controls are near-square, so the pill radii (`999`) go with the five themes.

- [ ] **Step 3: Remove the theme control from the header**

In `web/components/AppShell.tsx`:
- Change the import to `import { useThemePref } from './ThemeProvider'` only — delete `import { THEMES } from '@/lib/themes'`.
- Change the destructure at the top of the component from `const { themed, dark, setThemeName, setDark } = useThemePref()` to `const { dark, setDark } = useThemePref()`.
- Delete the `THEME` `<Text>` label and the `<Segmented>` that follows it (around lines 174-188). Leave the `DATA` label and its Segmented.

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: PASS. If it reports other files reading `themed` or `setThemeName`, fix each — `themed.accent` becomes `tokens.action`, `themed.darkBg`/`themed.lightBg` become `tokens.ground`.

- [ ] **Step 5: Run the e2e suite**

Run: `bash scripts/e2e-native.sh`
Expected: PASS. No spec asserts on theme names; if one does, update it.

- [ ] **Step 6: Commit**

```bash
git add web/lib/themes.ts web/components/ThemeProvider.tsx web/components/AppShell.tsx
git commit -m "refactor(web): replace the five themes with Instagram's palette"
```

---

### Task 6: Quota readout in the header

**Files:**
- Modify: `web/lib/api.ts:1-12` (`StatusBody`)
- Create: `web/components/UsageMeter.tsx`
- Modify: `web/components/AppShell.tsx` (header row, beside `Queue`)
- Test: `web/e2e/usage.spec.ts` (created in Task 8)

**Interfaces:**
- Consumes: `GET /api/status` `"usage": float | null` from Task 3; `Tokens` from Task 5.
- Produces: `<UsageMeter usage={number | null | undefined} />`, rendering `null`/`undefined` as nothing. Test id `usage-meter`.

- [ ] **Step 1: Extend the status type**

In `web/lib/api.ts`, add to `StatusBody`:

```ts
  queue_depth: number
  /** Percentage of Meta's hourly quota spent, as Meta last reported it.
   *  Null when the live adapter never calls Meta. */
  usage: number | null
```

- [ ] **Step 2: Write the component**

Create `web/components/UsageMeter.tsx`:

```tsx
'use client'

import { Tooltip, Typography } from 'antd'

import { useThemePref } from './ThemeProvider'

const { Text } = Typography

/** Meta backs the app off at 90%, so the colour tracks distance from that,
 *  not from 100. */
function colourFor(usage: number, warn: string, bad: string, calm: string): string {
  if (usage >= 75) return bad
  if (usage >= 50) return warn
  return calm
}

export default function UsageMeter({ usage }: { usage: number | null | undefined }) {
  const { tokens } = useThemePref()
  // Null means the live adapter never calls Meta. Rendering 0% there would
  // read as a measurement rather than an absence.
  if (usage === null || usage === undefined) return null

  const colour = colourFor(usage, '#fcb045', tokens.destructive, tokens.textSecondary)

  return (
    <Tooltip title="Share of Meta's hourly API quota spent. Requests stop at 90%.">
      <Text data-testid="usage-meter" style={{ fontSize: 12, color: colour }}>
        API {Math.round(usage)}%
      </Text>
    </Tooltip>
  )
}
```

No countdown, and no estimated reset. Meta sends no reset timestamp on Business Discovery calls, and a clock we invented would be read as one Meta gave us.

- [ ] **Step 3: Put it in the header**

In `web/components/AppShell.tsx`, import it:

```tsx
import UsageMeter from './UsageMeter'
```

and render it in the header row immediately before the `Queue` button:

```tsx
          <UsageMeter usage={status?.usage} />
          <Button size="small" type="text" onClick={() => setQueueOpen(true)}>
```

- [ ] **Step 4: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/api.ts web/components/UsageMeter.tsx web/components/AppShell.tsx
git commit -m "feat(web): show Meta's quota usage in the header"
```

---

### Task 7: Instagram profile header

**Files:**
- Modify: `web/lib/api.ts` (`ProfileDetail`)
- Create: `web/components/ProfileHeader.tsx`
- Modify: `web/app/p/[username]/page.tsx` (replace the current header row)
- Test: `bash scripts/e2e-native.sh`

**Interfaces:**
- Consumes: `followers_count` from Task 2; `GRADIENT` and `Tokens` from Task 5.
- Produces: `<ProfileHeader profile={ProfileDetail} indexed={number} actions={React.ReactNode} />`. Test ids: `profile-username`, `profile-stat-posts`, `profile-stat-followers`, `profile-stat-indexed`.

- [ ] **Step 1: Extend the profile type**

In `web/lib/api.ts`, add to `ProfileDetail`:

```ts
  followers_count: number | null
```

- [ ] **Step 2: Write the component**

Create `web/components/ProfileHeader.tsx`:

```tsx
'use client'

import { Avatar, Flex, Typography } from 'antd'

import type { ProfileDetail } from '@/lib/api'
import { GRADIENT } from '@/lib/themes'
import { useThemePref } from './ThemeProvider'

const { Text, Title } = Typography

function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`
  return String(n)
}

function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  const { tokens } = useThemePref()
  return (
    <Flex vertical gap={1} data-testid={testId}>
      <Text strong style={{ fontSize: 14 }}>{value}</Text>
      <Text style={{ fontSize: 11, color: tokens.textSecondary }}>{label}</Text>
    </Flex>
  )
}

export default function ProfileHeader({
  profile,
  indexed,
  actions,
}: {
  profile: ProfileDetail
  indexed: number
  actions: React.ReactNode
}) {
  const { tokens } = useThemePref()
  return (
    <Flex align="flex-start" gap={20} style={{ padding: '16px 20px 12px' }}>
      {/* The story ring is the one place the gradient appears. */}
      <div style={{ background: GRADIENT, padding: 2.5, borderRadius: '50%', flex: 'none' }}>
        <Avatar
          size={60}
          src={profile.avatar_url}
          style={{ border: `2px solid ${tokens.ground}` }}
        />
      </div>

      <Flex vertical gap={7} style={{ flex: 1, minWidth: 0 }}>
        <Title level={5} data-testid="profile-username" style={{ margin: 0 }}>
          {profile.username}
        </Title>

        <Flex gap={22}>
          <Stat testId="profile-stat-posts" label="posts" value={compact(profile.post_count)} />
          <Stat
            testId="profile-stat-followers"
            label="followers"
            value={compact(profile.followers_count)}
          />
          <Stat testId="profile-stat-indexed" label="indexed" value={String(indexed)} />
        </Flex>

        {profile.biography && (
          <Text style={{ fontSize: 12, color: tokens.textSecondary }}>{profile.biography}</Text>
        )}
      </Flex>

      {/* Track, sync and cache are things this app does, not things the
          profile is. They sit apart from Instagram's own furniture. */}
      <Flex gap={6} style={{ flex: 'none' }}>{actions}</Flex>
    </Flex>
  )
}
```

- [ ] **Step 3: Use it**

In `web/app/p/[username]/page.tsx`, replace the existing header row (the Flex holding the avatar, username, post count, `0 cached` tag, Track, sync and Clear cache buttons) with:

```tsx
<ProfileHeader
  profile={profile}
  indexed={media?.total ?? 0}
  actions={
    <>
      {/* the existing Track, sync and Clear cache buttons, unchanged */}
    </>
  }
/>
```

Move the existing button JSX into `actions` verbatim — do not rewrite the handlers. Import the component at the top.

- [ ] **Step 4: Typecheck and run e2e**

Run: `cd web && npx tsc --noEmit && cd .. && bash scripts/e2e-native.sh`
Expected: PASS. Specs referencing the old header markup by text may need their locators pointed at the new test ids.

- [ ] **Step 5: Commit**

```bash
git add web/lib/api.ts web/components/ProfileHeader.tsx "web/app/p/[username]/page.tsx"
git commit -m "feat(web): give the profile an Instagram header"
```

---

### Task 8: Tabs, seeded reels, and the e2e rewrite

**Files:**
- Modify: `web/lib/useFilters.ts:7-32`
- Modify: `web/app/p/[username]/page.tsx:239-252` (Segmented → tabs)
- Modify: `api/app/ig/fake.py:184-196` (`seeded_adapter`)
- Modify: `web/e2e/grid.spec.ts:6`
- Rewrite: `web/e2e/filters.spec.ts`
- Create: `web/e2e/tabs.spec.ts`, `web/e2e/usage.spec.ts`

**Interfaces:**
- Consumes: reel classification from Task 1; `UsageMeter` test id from Task 6; header test ids from Task 7.
- Produces: `KindFilter` becomes `'posts' | 'reels' | 'saved'`; `EMPTY_FILTERS.kind` is `'posts'`. Test id `profile-tabs` replaces `filter-kind`.

- [ ] **Step 1: Seed two reels**

In `api/app/ig/fake.py`, add one line to `seeded_adapter`:

```python
    adapter = FakeAdapter()
    adapter.add_profile("nike", post_count=8)
    adapter.add_posts("nike", count=6)
    adapter.add_posts("nike", count=2, child_count=3)
    # Two reels: without them the REELS tab has nothing to prove itself on.
    adapter.add_posts("nike", count=2, video=True)
    return adapter
```

The dataset becomes nike-0..5 photos, nike-6..7 carousels, nike-8..9 reels — ten items, eight of them POSTS.

- [ ] **Step 2: Confirm the grid spec still holds**

`web/e2e/grid.spec.ts:6` asserts `toHaveCount(8)`. POSTS is the default tab and excludes the two new reels, so eight is still right and **no edit is expected**. Run it and confirm rather than assuming:

Run: `bash scripts/e2e-native.sh -- grid.spec.ts` (or `cd web && npx playwright test grid.spec.ts` against an already-running e2e stack)
Expected: PASS unchanged. If it fails at `10`, the tab default is wrong — fix Task 8 Step 3, not the assertion.

Note the seeded timestamps: `add_posts` dates items `2026-01-{(i % 28) + 1}`, so the reels (nike-8, nike-9) are the *newest* items in the dataset. Any spec asserting "newest first" on the default tab now sees nike-7 at the front, not a reel.

- [ ] **Step 3: Rewrite the filter model**

In `web/lib/useFilters.ts`:

```ts
export type KindFilter = 'posts' | 'reels' | 'saved'

export type Filters = {
  kind: KindFilter
  cachedOnly: boolean
  query: string
}

export const EMPTY_FILTERS: Filters = { kind: 'posts', cachedOnly: false, query: '' }

/** Instagram splits its grid by the surface a post was published to, not by
 *  file type. Saved is ours: what this app has actually pulled down. */
export function matchesKind(item: MediaSummary, kind: KindFilter): boolean {
  if (kind === 'reels') return item.kind === 'reel'
  if (kind === 'saved') return item.full_status === 'ready'
  return item.kind !== 'reel'
}
```

`applyFilters` and `useFilters` below it are unchanged — they already delegate to `matchesKind`.

- [ ] **Step 4: Swap the control for tabs**

In `web/app/p/[username]/page.tsx`, replace the kind `<Segmented>` (around line 239) with:

```tsx
        <Segmented
          size="small"
          data-testid="profile-tabs"
          value={filters.kind}
          onChange={(v) => setFilters({ ...filters, kind: v as KindFilter })}
          options={[
            { value: 'posts', label: 'POSTS' },
            { value: 'reels', label: 'REELS' },
            { value: 'saved', label: 'SAVED' },
          ]}
        />
```

Keep the caption search, cached-only toggle, count, Reset and the rest of the row exactly as they are.

The `filtersActive` check just below reads `filters.kind !== 'all'`; change it to `filters.kind !== 'posts'` so Reset still lights up correctly.

- [ ] **Step 5: Rewrite `filters.spec.ts`**

Replace the file's kind-filter tests. `pickKind` becomes:

```ts
// antd Segmented renders labelled radios, not a native <select>. The label,
// not the input, is what is actually clickable.
const pickTab = (page: import('@playwright/test').Page, label: string) =>
  page.getByTestId('profile-tabs').getByText(label, { exact: true }).click()
```

Delete `test('kind filter narrows the grid to carousels')` and `test('photos filter excludes the carousels')` — carousels are no longer separable, which is a recorded, accepted loss. Update the three tests that assert `toHaveCount(8)` and `'... of 8 shown'`: on the default POSTS tab the dataset is still eight, so those hold. In `test('reset restores the full grid')`, swap the `pickKind(page, 'Carousels')` for `pickTab(page, 'REELS')` and the intermediate expectation to `toHaveCount(2)`. Same substitution in `test('select all respects the active filter')`, whose final assertion becomes `'2 selected'`.

- [ ] **Step 6: Write the tab spec**

Create `web/e2e/tabs.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

// Seeded: nike-0..5 photos, nike-6..7 carousels, nike-8..9 reels.

const tiles = (page: import('@playwright/test').Page) =>
  page.getByTestId('media-grid').locator('.tile')

const pickTab = (page: import('@playwright/test').Page, label: string) =>
  page.getByTestId('profile-tabs').getByText(label, { exact: true }).click()

test('posts is the default tab and excludes reels', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(tiles(page)).toHaveCount(8)
  await expect(page.getByTestId('tile-nike-8')).toHaveCount(0)
})

test('reels shows only reels', async ({ page }) => {
  await page.goto('/p/nike')
  await pickTab(page, 'REELS')

  await expect(tiles(page)).toHaveCount(2)
  await expect(page.getByTestId('tile-nike-8')).toBeVisible()
  await expect(page.getByTestId('tile-nike-0')).toHaveCount(0)
})

test('saved shows only what has been downloaded', async ({ page }) => {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>, idx: number) => ({
      ...i,
      full_status: idx < 3 ? 'ready' : 'none',
    }))
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await pickTab(page, 'SAVED')

  await expect(tiles(page)).toHaveCount(3)
})

test('the header reports posts, followers and indexed', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('profile-username')).toHaveText('nike')
  await expect(page.getByTestId('profile-stat-posts')).toBeVisible()
  await expect(page.getByTestId('profile-stat-indexed')).toBeVisible()
})
```

- [ ] **Step 7: Write the usage spec**

Create `web/e2e/usage.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('the quota readout is hidden when the adapter does not call Meta', async ({ page }) => {
  // The e2e stack runs the fake adapter, which reports no usage at all.
  await page.goto('/')
  await expect(page.getByTestId('usage-meter')).toHaveCount(0)
})

test('the quota readout shows the reported percentage', async ({ page }) => {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({ response: res, json: { ...body, usage: 42 } })
  })

  await page.goto('/')

  await expect(page.getByTestId('usage-meter')).toHaveText('API 42%')
})
```

- [ ] **Step 8: Verify the tabs actually gate the grid**

Temporarily change `matchesKind` in `web/lib/useFilters.ts` to `return true` for every branch, run `bash scripts/e2e-native.sh`, and confirm `tabs.spec.ts` fails. Then restore it. A tab test that passes against a control that does nothing is worth nothing.

- [ ] **Step 9: Run both suites**

Run: `cd api && ../.venv/Scripts/python.exe -m pytest -q`
Run: `cd .. && bash scripts/e2e-native.sh`
Expected: both PASS.

- [ ] **Step 10: Commit**

```bash
git add api/app/ig/fake.py web/lib/useFilters.ts "web/app/p/[username]/page.tsx" web/e2e
git commit -m "feat(web): split the profile grid into Posts, Reels and Saved"
```

---

## Verification

Before calling this done:

- [ ] `cd api && ../.venv/Scripts/python.exe -m pytest -q` — green
- [ ] `bash scripts/e2e-native.sh` — green
- [ ] `cd web && npx tsc --noEmit` — clean
- [ ] Boot the real stack against Graph and open `/p/nike`: twelve tiles on first load, REELS holds reels, the header shows a follower count, and `API n%` appears beside Queue.
