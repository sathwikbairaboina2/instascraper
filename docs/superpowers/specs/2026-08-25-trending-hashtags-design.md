# Trending hashtags, by day and by week

**Date:** 2026-08-25
**Status:** approved, implementation in progress

## Why

The app can already tell you which single post did well. It cannot tell you
what *subject* is doing well, which is the question you actually ask before
deciding what to make next. Captions carry that answer already -- every post
we have cached names its own topics with hashtags -- and nothing reads them.

This design ranks hashtags by the engagement of the posts carrying them,
over two windows, and puts the result in front of you as a feed you can act
on: expand a tag, see its posts, push them into the recreate queue that
already exists.

## Scope

Two windows only: **day** (posts published in the last 24h) and **week**
(last 7 days). No month, no all-time, no custom range. A range picker is a
different feature and would earn its own design.

The pool is **every cached post**, across all synced profiles -- not just the
recreate queue. Ranking a handful of hand-marked items would produce numbers
that look like a trend and are not one.

## Where the tags come from

Parsed from `media_items.caption` at query time. Not stored, not
materialised.

That is a deliberate bet on the window doing the bounding: `taken_at >=
now - 24h` (or `- 7d`) restricts the scan to recent posts, which is a small
slice of the table no matter how large the table grows. Extraction lives in
`app/services/hashtags.py` as pure functions over strings, so if the bet
ever stops paying, a `post_hashtags` table can be populated at index time
and swapped in underneath without the route or the UI noticing.

### Extraction rules

- A `#` counts only at the start of the caption or after whitespace. This is
  what keeps `example.com/#anchor` and `C#` inside a word out of the results.
- The tag body is letters, digits and underscore, including non-ASCII
  letters. Instagram allows non-Latin tags and dropping them would quietly
  make the feature English-only.
- Trailing punctuation is not part of the tag: `#nike,` is `#nike`.
- Tags are case-folded. `#Nike` and `#nike` are one row, because they are one
  tag on Instagram.
- A tag repeated within one caption counts **once**. Otherwise a caption that
  spams `#sale #sale #sale` outranks a post people actually engaged with.
- `#` alone, and `#` followed only by punctuation, are not tags.

## Score

    score = sum(like_count) + sum(comments_count) + sum(view_count)

over the posts in the window carrying the tag, counting `NULL` as zero.

Each component is returned alongside the total, together with `post_count`,
so the UI can show the breakdown and you can see *why* something ranks.

Ordering is `score DESC, post_count DESC, tag ASC`. The tie-break is not
decoration: without a total order, two pages of an offset-paged list can
repeat a row or skip one.

**Known bias, accepted.** `view_count` exists on reels and nowhere else, so
a plain sum lets reels outweigh images by an order of magnitude. This is the
formula that was chosen with that trade-off stated. If it proves wrong in
use, the fix is a weighting constant in one function.

## API

Both endpoints follow the existing `limit` / `offset` / `total` convention
established by `/api/profiles/{username}/media`.

    GET /api/hashtags/trending?window=day|week&limit=25&offset=0

```json
{
  "window": "day",
  "since": "2026-08-24T22:10:00+00:00",
  "total": 42,
  "items": [
    {
      "tag": "justdoit",
      "score": 91234,
      "like_count": 80000,
      "comments_count": 1234,
      "view_count": 10000,
      "post_count": 7
    }
  ]
}
```

`tag` is returned without the leading `#`; the UI adds it. An unknown
`window` is a 400, not a silent fallback to a default -- a typo that
silently returns the wrong window is worse than an error.

    GET /api/hashtags/{tag}/posts?window=day|week&limit=24&offset=0

Returns rows in the same shape the media grid already consumes, via the
existing `_media_summary` serializer, so the UI has nothing new to learn.

A tag nobody used in the window returns an empty list and `total: 0`, not a
404. A tag that has fallen out of the window is not an error, and the
distinction between "never existed" and "not trending now" is one this
endpoint has no way to make honestly.

## UI

A new page at `/trending`, reached from the nav in `AppShell`.

- `Day | Week` as a `Segmented`, matching the tab pattern already used on
  profiles and the recreate list.
- Rows: rank, `#tag`, score through the existing `compactCount` formatter,
  and post count. The formatter is already shared between tiles and the
  profile header; a third copy of the rounding rule is exactly the drift
  this codebase has been bitten by before.
- **Load more** appends the next offset page. It disappears once
  `items.length >= total`.
- Expanding a row fetches that tag's posts and shows them as thumbnails.
  Select some, press **Mark for recreate**, and they go through the existing
  `POST /api/recreate`; the queue badge updates through `RecreateProvider`.

### Empty states are honest

The day window will often be empty on real Graph data, because cached posts
are usually older than 24 hours. The empty state says that -- "no posts
published in the last 24 hours are cached" -- rather than a decorative "no
trends yet" that reads identically to a broken query.

## Test data

The fake adapter currently generates captions of the form `caption {i}`,
with no hashtags, at fixed dates in January 2026. Against that dataset both
windows are permanently empty and no end-to-end test of this feature can
mean anything.

So the fake dataset grows two properties, both of which it arguably should
have had already:

- captions carrying hashtags, with a deliberate overlap between posts so
  that ranking has something to rank;
- engagement counts, and posts dated relative to now rather than pinned to
  January, so that "the last 24 hours" contains something.

Relative dates are computed once per adapter instance rather than per call,
so a test that reads the same post twice sees the same date both times.

## Testing

Unit (`pytest`):

- extraction: case-folding, per-post dedupe, trailing punctuation, non-ASCII
  tags, the URL-anchor case, bare `#`, empty and `NULL` captions;
- ranking: `NULL` components counted as zero, the tie-break, ordering;
- the window boundary: a post exactly at the cutoff, on both sides;
- paging: `total` correct, adjacent pages neither overlap nor skip;
- `400` on an unrecognised window, on both endpoints;
- the tag-posts endpoint, including the empty-tag case.

End-to-end (`Playwright`):

- the page loads under both windows and switching refetches;
- load more appends and does not duplicate;
- expanding a row lists that tag's posts;
- marking from an expanded row lands the post in the recreate queue and
  moves the badge;
- the empty window renders the honest empty state.

Both full suites -- backend and e2e -- must pass before this is committed,
not just the new tests.

## Rejected

- **A materialised `post_hashtags` table.** Correct at a scale this app does
  not have, and it buys a write path, a backfill, and a way for the index to
  drift from the captions it came from.
- **A hashtag search box.** Adjacent, useful, and not this feature.
- **Ranking by average engagement per post.** Hands the top of the feed to
  whichever tag rode one viral post.
