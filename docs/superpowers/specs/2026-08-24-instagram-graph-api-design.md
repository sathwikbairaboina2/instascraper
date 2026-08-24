# Instagram Graph API adapter — design

Date: 2026-08-24
Status: approved design, ready for an implementation plan
Branch: `feat/graph-api-adapter`

## Why

instascraper is feature-complete but has never fetched a real post. The
Instaloader adapter cannot get data: Instagram returns 429 to this IP
anonymously, and logging in with a personal account was ruled out. A
survey of anonymous mirror sites (imginn, pixnoy, dumpor and eleven
others) found every one of them either Cloudflare-walled against any
automated client or no longer serving content at all.

Meta's Business Discovery endpoint solves the problem officially. It
returns public profile and media data for Instagram Business and
Creator accounts, which is exactly the scope this tool targets. No bot
gate, no IP rate-limit fight, no scraping.

## Goal

Replace Instaloader with a `GraphAdapter` that satisfies the existing
`IgAdapter` protocol, so the worker, database, API, and web UI keep
working unchanged.

## Non-goals

- Personal (non-Business, non-Creator) accounts. Business Discovery
  cannot see them. This is a permanent limitation, not a gap to close.
- Stories, highlights, and tagged media of other accounts. Meta exposes
  none of these for accounts you do not own.
- Comment text, follower lists, and insights for other accounts.
- Automatic OAuth token refresh. See "Token lifecycle".

## Prerequisites (manual setup, performed by the operator)

Business Discovery is a nested field on *your own* Instagram Business
account node, so the tool needs an account of its own. None of this can
be automated.

1. Convert an Instagram account to **Business** or **Creator**
   (Instagram app: Settings, Account type and tools).
2. Create or choose a **Facebook Page**.
3. **Link** the Instagram account to that Page. Business Discovery is
   only available through the Facebook-Login flavour of the Instagram
   API, so this link is mandatory.
4. Create a **Meta developer app** at developers.facebook.com, type
   Business, and add the Instagram product.
5. Grant the token these permissions: `instagram_basic`,
   `pages_show_list`, `pages_read_engagement`, `business_management`.
6. Obtain the **Instagram user id**: `GET /me/accounts` to find the Page
   id, then `GET /{page-id}?fields=instagram_business_account`.
7. Prefer a **Business Manager system-user token**, which does not
   expire, over a long-lived user token, which expires after 60 days.

A single-operator tool running in Development Mode uses assets you own,
so App Review is not expected to be required. Confirm this during
implementation; if Meta disagrees, the failure is loud and immediate
(`IgChallenge` at startup), not silent.

Cost: none. Business Discovery is free.

## Architecture

Two new flat modules, matching the existing `app/ig/` layout:

- `app/ig/graph.py` — `GraphAdapter` plus a thin HTTP client for
  `graph.facebook.com`, built on `httpx`, which is already a project
  dependency. No new package is added; removing Instaloader in fact
  drops `requests` and its transitive tree.
- `app/ig/graph_map.py` — pure functions mapping Meta JSON onto
  `IgProfile` and `IgPost`. Kept separate and side-effect free because
  this is the code that breaks when Meta reshapes a response, and
  purity makes it testable against recorded fixtures with no network.

`make_adapter()` returns `GraphAdapter` by default. The `"fake"` branch
remains, documented as test-only: the Playwright suite drives a live
server whose lightbox specs trigger a real `media_fetch`, so the e2e
environment needs a working adapter at runtime.

### Configuration

Added to `Settings`, all environment-driven:

| Variable | Meaning | Default |
|---|---|---|
| `IG_GRAPH_TOKEN` | Access token | none, required |
| `IG_GRAPH_USER_ID` | Your own IG Business account id | none, required |
| `IG_GRAPH_VERSION` | Pinned Graph API version | none, required — set during setup from Meta's current version, never hardcoded in source |
| `IG_GRAPH_REFRESH_PAGES` | Bounded search depth when refreshing a stale URL | 2 |
| `IG_GRAPH_USAGE_LIMIT` | `X-App-Usage` percentage at which to stop spending | 90 |

Removed from `Settings` with Instaloader: `ig_username`, `ig_password`,
`session_dir`, `anonymous`, `max_sleep`. The entire anonymous-mode
branch in `load_settings()` goes with them; it existed only to let a
credential-less Instaloader degrade gracefully.

`IG_MIN_INTERVAL` stays — it drives `app/worker/pacer.py`, which is
unrelated to the deleted Instaloader rate controller.

## Port changes

Two, both additive and both defaulted so the fake adapter is unaffected.

**1. `IgPost` carries its media sources.**

```python
@dataclass(frozen=True)
class MediaSource:
    child_idx: int
    url: str
    mime: str
    is_video: bool
```

`IgPost` gains `sources: tuple[MediaSource, ...] = ()`. Without this
the handler has nothing to persist, and full-quality media becomes
unreachable — see "The freshness problem".

`child_idx` follows the existing convention already used by the fake
adapter and `paths.full_filename`: `0` for a single-media post, `1..N`
for the children of a carousel. `mime` is derived from `media_type` —
`video/mp4` for VIDEO, `image/jpeg` otherwise — since Meta does not
return a content type in the listing.

**2. `fetch_media` accepts a hint.**

`fetch_media(shortcode, dest_dir, hint=None)` where `hint` is a frozen
dataclass carrying `username`, the cached sources, and their capture
time. Refreshing a stale URL requires knowing which account a post
belongs to, and the adapter has no database access. `handle_media_fetch`
already reads the `media_items` row, so it builds the hint from data it
is holding.

The five-case error model needs no new members.

## The freshness problem

Business Discovery has no per-media endpoint. `GET /{media-id}` on
another account's media fails with insufficient permissions. Media URLs
are obtainable *only* inside a listing response, and Meta's CDN URLs
expire.

The tool's usage pattern — many accounts, shallow indexing — makes this
cheap to solve. Any post the operator would open is recent, so it is
still on page one of a fresh listing.

Chosen strategy, **refresh on demand**:

1. `fetch_page` records each post's sources and the capture time.
2. `fetch_media` tries the cached URLs first.
3. On 403, 404, or 410 from the CDN, re-list the profile, page up to
   `IG_GRAPH_REFRESH_PAGES`, match on shortcode, download from the
   fresh URLs.
4. Not found within the bound raises `IgNotFound` with a "too far back,
   re-sync this profile" message. Terminal, because retrying cannot
   help.

Rejected alternatives: eager full download at index time (never stale,
but wastes bandwidth and disk across many accounts whose posts are
mostly never opened) and a snapshot window (simplest, but converts a
silent recovery into a user-visible failure).

## Data flow

### Profile sync — one call

```
GET /{version}/{IG_GRAPH_USER_ID}
  ?fields=business_discovery.username({target}){
      id,ig_id,username,name,biography,followers_count,media_count,profile_picture_url
  }
```

| `IgProfile` | Source |
|---|---|
| `username` | `username` |
| `user_id` | `id` |
| `full_name` | `name` |
| `biography` | `biography` |
| `is_private` | always `False` — Business Discovery only returns public Business/Creator accounts |
| `post_count` | `media_count` |
| `avatar_url` | `profile_picture_url` |

The avatar downloads over plain HTTP with no token attached.

### Page fetch — one call per page

```
GET /{version}/{IG_GRAPH_USER_ID}
  ?fields=business_discovery.username({target}){
      media.limit({limit}).after({cursor}){
          id,caption,media_type,media_product_type,media_url,
          thumbnail_url,permalink,timestamp,
          children{id,media_type,media_url,thumbnail_url}
      }
  }
```

`.after(...)` is omitted when the cursor is null.

| `IgPost` | Source |
|---|---|
| `shortcode` | parsed from `permalink` |
| `kind` | `media_type`, with `/reel/` in the permalink distinguishing reels from plain video |
| `taken_at_iso` | `timestamp` |
| `caption` | `caption` |
| `is_video` | `media_type == "VIDEO"` |
| `child_count` | number of `children`, else 1 |
| `thumb_url` | `media_url` for images, `thumbnail_url` for video, first child for carousels |
| `ig_url` | `permalink` |
| `sources` | one `MediaSource` per child; `media_url` on a VIDEO is the MP4, so full-quality video works |

`next_cursor` comes from the nested `paging.cursors.after`. Its absence
means exhausted, matching the existing empty-string convention in
`profiles.next_cursor`.

The existing `first_page_size` (3) and `page_size` (36) map directly
onto `media.limit(...)`, preserving today's behaviour: a cheap first
look, full pages on "Load more".

### Media fetch

Handler builds the hint from the row; adapter follows the refresh
strategy above. Thumbnail downloading is unchanged existing code. The
only new write during page fetch is `src_urls`.

## Storage

`media_items` gains two columns:

- `src_urls TEXT` — JSON array of `MediaSource`
- `src_urls_at TEXT` — ISO capture timestamp

SQLite has no `ADD COLUMN IF NOT EXISTS` and the project has no
migration system — `schema.sql` is one idempotent script run at
startup. So `db.py` gains a small `migrate(conn)` that reads
`PRAGMA table_info` and adds missing columns, called immediately after
`init_schema`. Existing databases, including the demo dataset, keep
working.

## Error handling

Meta replies HTTP 400 with `{"error": {message, type, code, error_subcode}}`.

| Meta | Mapped to | Rationale |
|---|---|---|
| `190`, `102`, `200`–`299` | `IgChallenge` | Dead or under-scoped token. Breaker trips hard; retrying cannot fix a revoked token. |
| `4`, `17`, `32`, `613` | `IgRateLimited` | App, user, page, and custom throttling. |
| Unknown username | `IgNotFound` | Terminal. |
| Target is not Business/Creator | `IgPrivate` | Reuses "exists, out of scope", which is what a personal account is here. |
| `1`, `2`, HTTP 5xx, timeouts, connection errors | `IgTransient` | Retryable. |
| Anything unrecognised | `IgTransient` | Matches how the current `classify()` defaults. |

The exact code Meta returns for a personal-account target is the one
mapping not yet confirmed. Implementation captures a real response,
pins it as a fixture, and sets the mapping from observed behaviour.

## Rate limits

Meta sends no `Retry-After`, but throttling responses carry
`estimated_time_to_regain_access` in minutes. Converted to seconds it
populates `IgRateLimited.retry_after`, which the breaker already
honours — strictly better than the blind `IG_BACKOFF=900` fallback
Instaloader forced.

Every response also carries `X-App-Usage` with a `call_count`
percentage. When it crosses `IG_GRAPH_USAGE_LIMIT`, the adapter raises
`IgRateLimited` before spending the call, so the tool backs off rather
than walking into a lockout.

Business Discovery is subject to Platform Rate Limits rather than the
stricter per-user Instagram limits.

## Security

- The token travels in an `Authorization: Bearer` header, never as an
  `access_token` query parameter. Meta accepts both, but the query form
  puts a live credential into every URL, and from there into exception
  strings, the JSON logs, and the `activity_log` table.
- Error text echoed from Meta passes through a redaction guard before
  being logged or stored.
- Recorded test fixtures are redacted before they are committed: token,
  the operator's own IG user id, and `fbtrace_id`.

## Token lifecycle

`login()` becomes token validation — one cheap call at startup, raising
`IgChallenge` on failure so the UI shows a real "token expired" state
instead of failing mysteriously on each request.

No automatic refresh. Refreshing a long-lived user token requires the
app secret in configuration, and there is a better answer for a
single-operator tool: a Business Manager system-user token, which does
not expire. The setup instructions steer to that, which removes token
expiry as a recurring chore.

## Testing

Nothing in the default suite touches the network.

1. **Fixture-backed mapping tests** for `graph_map.py`: image post,
   video post, carousel with children, profile, empty media edge, final
   page with no `after` cursor. Fixtures live in
   `tests/fixtures/graph/` and are captured by a small dev script that
   makes one real call, then redacted.
2. **Adapter tests with an injected transport.** `GraphAdapter` takes
   its HTTP callable as a constructor argument; tests supply a stub
   returning canned `(status, headers, body)`. Covers: field string
   construction, cursor threading into `.after()`, `limit` handling,
   stale URL triggering refresh, bounded search stopping at
   `IG_GRAPH_REFRESH_PAGES`, and a refresh miss raising `IgNotFound`
   rather than looping.
3. **Parametrized error-classification table**: Meta envelope in,
   `IgError` subclass out.
4. **Existing coverage preserved.** Handler and API tests keep running
   on `FakeAdapter`; the Playwright suite keeps running on
   `seed_e2e.py`. `test_ig_contract.py` extends to assert `GraphAdapter`
   satisfies the protocol alongside the fake.
5. **Opt-in live canary.** `test_live_canary.py` is rewritten against
   Graph and skipped unless `IG_GRAPH_TOKEN` is set. One real call to a
   known public business account, asserting response shape rather than
   content, so it cannot fail because an account posted something new.

Implementation is test-first.

## Removals

Instaloader's footprint reaches further than the adapter module, and
every one of these is part of the work.

**Source:**

- `app/ig/adapter.py` — the Instaloader adapter and its `classify()`.
- `app/ig/rate.py` — `PacedRateController`, an Instaloader-specific
  rate controller. Distinct from `app/worker/pacer.py`, which stays.
- `app/ig/login.py` — the `python -m app.ig.login` entrypoint. It
  exists solely to create an Instaloader session file from
  `IG_USERNAME` / `IG_PASSWORD`, all three of which are going away. The
  Graph adapter has no interactive login step; `login()` is token
  validation.

**Tests:**

- `tests/test_adapter_parse.py` — parses Instaloader node dicts.
- `tests/test_anonymous_mode.py` — anonymous mode no longer exists.
- `tests/test_login_entrypoint.py` — its subject is deleted.
- `test_ig_contract.py::test_only_adapter_module_imports_instaloader` —
  a guard that no module outside the adapter imports Instaloader.
  Meaningless once nothing imports it; deleted rather than retargeted,
  since `graph_map.py` being pure is already asserted by its own tests
  running without a transport.
- `tests/test_backoff_respect.py` is **retargeted, not deleted** — its
  real subject is the breaker honouring `retry_after`, which still
  matters, now driven by `estimated_time_to_regain_access`.

**Configuration and deployment:**

- `requirements.txt` — drop `instaloader==4.14.1`.
- `.env.example` — drop `IG_USERNAME`, `IG_PASSWORD`, `IG_ANONYMOUS`
  and their comments; add the five `IG_GRAPH_*` variables.
- `docker-compose.yml` — drop the `SESSION_DIR` environment entry and
  the session volume path it implies.
- `CHANGELOG.md` references `python -m app.ig.login` as historical
  record; it is left untouched, as is the superseded plan document at
  `docs/superpowers/plans/2026-08-23-instascraper.md`. Both describe
  what was true when written.

## Success criteria

1. `IG_ADAPTER` unset or `graph` fetches a real public Business or
   Creator profile, indexes its recent posts, and renders thumbnails in
   the web UI.
2. Opening a post in the lightbox downloads full-quality media,
   including video.
3. A post whose cached URL has expired still opens, via the refresh
   path, without operator intervention.
4. An expired or revoked token produces a clear UI state, not an
   unexplained failure.
5. The full backend suite and all Playwright specs pass with no
   network access.
6. No token value appears in logs, the `activity_log` table, or any
   committed fixture.
