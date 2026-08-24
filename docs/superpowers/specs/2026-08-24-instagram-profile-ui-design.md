# Instagram-shaped profile, live quota readout, bigger first page

**Date:** 2026-08-24
**Status:** approved, not yet implemented

## Why

The profile page is a dense tool surface: a Segmented control of
All/Photos/Video/Carousels, a caption search, a cached-only toggle and a
selection rail. It works, but it looks nothing like the thing it indexes.
This redesign brings the page close to Instagram's own profile without
giving up the fact that this is a downloader, not a viewer.

Two smaller features ride along: the app should say how much of Meta's
hourly quota it has spent, and it should stop showing three posts when a
profile is first opened.

## What Business Discovery cannot do

Probed live against `nike` on 2026-08-24, v25.0. Recorded here so it is not
re-investigated later:

| Asked for | Result |
| --- | --- |
| Highlights | `(#100) Tried accessing nonexisting field (story_highlights)`. Also fails as `highlights`. The field does not exist in the API. |
| Stories | `business_discovery{stories{id}}` returns the profile id and nothing else -- no error, no data. The `stories` edge exists only on your own IG User node (`/{my-id}/stories`). Other accounts' stories are never returned. |
| Tagged | `(#10) Application does not have permission` on both `business_discovery{tags}` and `/{my-id}/tags`, with `instagram_manage_insights` already granted. |
| Reels | Available. `media_product_type` is `REELS` or `FEED`; 18 of nike's last 36 were reels. |

No scope, app review, or account type unlocks the first three. The tabs
Instagram shows for Highlights, Tagged and Stories are therefore not built.
A profile page that renders them empty forever would be a promise the app
cannot keep.

## Layout

Instagram's shell, the tool's working surfaces intact ("Hybrid" of the three
options reviewed):

- Gradient avatar ring, username, stats row (`posts / followers / indexed`),
  bio line.
- Track / Sync / Clear cache as a right-hand action group. These are tool
  actions, not profile actions, so they do not sit under the bio where
  Instagram puts Follow and Message.
- Centred, letter-spaced tab bar under the header.
- Filter row below the tabs: caption search, cached-only, Reset, visible
  count, grid/table switch, Select all, Load more.
- Selection rail on the right, unchanged. Lightbox unchanged.

### Tabs

| Tab | Contents | Predicate |
| --- | --- | --- |
| POSTS | images, carousels, non-reel video | `media_product_type = FEED` |
| REELS | reels | `media_product_type = REELS` |
| SAVED | anything downloaded to disk | `full_status = 'ready'` |

SAVED is ours rather than Instagram's, and it fills the slot where
Highlights sits on a real profile. It is the one tab that is about this
app's own work.

The tab drives `filters.kind`; `useFilters` keeps its shape, so selection
and download logic are untouched.

**Accepted loss:** carousels can no longer be isolated. Inside POSTS they
mix with photos, distinguished only by the tile's child-count badge.

## Palette

The five themes (Graphite, Coral, Lime, Iris, Sea) are replaced by one
Instagram token set with dark and light variants. Dark stays the default;
the Dark toggle stays in the header. `lib/themes.ts` shrinks to a token
file and the theme Segmented leaves the header.

| Token | Dark | Light |
| --- | --- | --- |
| ground | `#000000` | `#ffffff` |
| surface | `#121212` | `#fafafa` |
| hairline | `#262626` | `#dbdbdb` |
| text | `#f5f5f5` | `#000000` |
| text secondary | `#a8a8a8` | `#737373` |
| action | `#0095f6` | `#0095f6` |
| destructive | `#ed4956` | `#ed4956` |

The story gradient (`#fcb045 -> #fd1d1d -> #833ab4`) appears on the avatar
ring and nowhere else. Instagram uses it sparingly; spread across buttons it
reads as imitation.

antd's `ConfigProvider` takes these as `colorPrimary`, `colorBgBase`,
`colorBorder`, `colorError`.

## Reel detection

`graph_map.py:92` infers reels from `"/reel/" in permalink`. Checked against
live data, the guess agrees with `media_product_type` on every sampled post
-- but the field is Meta's definition and the URL shape is a proxy for it.
Switch to the field. It is already requested in `_MEDIA_FIELDS` and
currently discarded.

## Followers count

`profiles` gains `followers_count INTEGER` through the existing migration
map in `db.py:65`. Business Discovery already returns it and
`profile_from_payload` currently drops it. It is the middle stat in the
header.

## Quota readout

Meta sends exactly one usage header on Business Discovery calls:

```
x-app-usage: {"call_count":13,"total_cputime":0,"total_time":22}
```

`call_count` is a percentage of the hourly quota, not a count.

**There is no reset timestamp.** `x-business-use-case-usage` -- the header
carrying `estimated_time_to_regain_access` -- is never present on these
calls.

So the header shows the usage figure and nothing else: `API 13%`, its colour
shifting toward the 90% backoff threshold as it climbs. No countdown. A
reset time could be estimated from our own call timestamps, but an invented
clock reads as fact to whoever is looking at it, and this readout exists to
be trusted. Rejected deliberately.

Known and not addressed here: `graph.py:67` parses `x-business-use-case-usage`
for `retry_after`, and Meta never sends that header on these calls, so
`retry_after` on a 429 is always `None`. Worth its own fix; out of scope for
this work.

**Required fix:** `graph.py:157` keeps `self._usage = max(self._usage, ...)`,
so usage only climbs for the life of the process and never reflects the
hourly reset. Correct as a backoff guard, wrong as a readout. The adapter
keeps both: latest value for display, high-water mark for the 90% backoff.
`/api/status` gains a `usage` block; the header polls it like it already
polls queue depth.

## First page size

`FIRST_PAGE_SIZE` moves from 3 to 12 -- one full screen of the 3-up grid.

The 3 was a scraper-era number whose reason no longer holds. Measured: a
page of 200 posts costs exactly one Graph call, the same as a page of 3.
`media.limit(200)` returned 200 items and moved `call_count` by one
increment. The first-page limit saves nothing on the quota.

The real cost is thumbnails, and those come from
`scontent.cdninstagram.com`, which does not touch `x-app-usage` at all. The
expense is `handlers.py:119`: `ctx.pacer.wait()` before every thumbnail at
`IG_MIN_INTERVAL=3`. Twelve posts would be thirty-six seconds of deliberate
waiting for no quota benefit.

So the pacer splits. Graph calls keep the three-second interval. CDN
downloads get `IG_CDN_MIN_INTERVAL`, default 0.5s, which puts twelve posts
on screen in roughly six seconds. Env-configurable, so restoring the old
caution is one line. Pacing the CDN at all is prudent; pacing it like a
scraped endpoint is not.

## Testing

- Backend: reel mapping from `media_product_type`; `followers_count`
  mapped and migrated; usage parsing keeps latest and high-water
  separately; `/api/status` reports usage. A dropping usage figure must
  survive the round trip -- the high-water mark guarding backoff must not
  leak into the readout.
- `web/e2e/filters.spec.ts` asserts on `filter-kind` and will fail by
  design. Rewritten against the tabs.
- New e2e: each tab shows its own subset; SAVED shows only downloaded
  items; the quota readout renders.
- Both suites must be green before this is called done.

## Order of work

1. Reel mapping and `followers_count` (backend, tested)
2. Usage tracking and `/api/status` exposure
3. Pacer split and `FIRST_PAGE_SIZE`
4. Theme tokens replace the five themes
5. Profile header
6. Tabs
7. e2e rewrite and additions

Backend first throughout: every UI step lands on data that already works.
