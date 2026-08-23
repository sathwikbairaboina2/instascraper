# Design: Instagram Content Retrieval Tool

**Status:** Approved
**Date:** 2026-08-23
**Source PRD:** `instagram-content-tool-prd.md`

## 1. Scope changes from the PRD

The PRD describes a shared team tool on AWS. Decisions taken during brainstorming narrow it:

| PRD said | Design says | Why |
|---|---|---|
| NestJS API | FastAPI | Instaloader is Python; one language removes a service boundary |
| DynamoDB | SQLite on a mounted volume | All-local deployment, single user, small relational access patterns |
| S3 | Plain files on a mounted volume | No S3 API needed locally; Instaloader already writes to disk |
| AWS hosting | Docker Compose, fully local | Explicit decision |
| Multiple content managers, flat access | **Single user** | Explicit decision |
| Activity log of "who did what" | Personal history log, no actor field | Single user makes attribution meaningless |
| Shared list of tracked profiles | Personal list of tracked profiles | Same |
| Download via browser | Files written to a bind-mounted host folder | Browsers throttle bulk programmatic downloads; a local tool has a better option |

Unchanged from the PRD: public profiles only, no write access to Instagram, no full-history bulk archiving in one pass, one dedicated Instagram identity, all Instagram traffic serialized.

## 2. Architecture

Two containers.

**`web`** — Next.js (App Router). Publishes `:3000`. `next.config` rewrites `/api/*` to `http://api:8000/*`, giving the browser a single origin and removing any need for CORS handling.

**`api`** — FastAPI on uvicorn, **`--workers 1` (non-negotiable)**. Two threads of execution:

- the uvicorn event loop — serves HTTP, reads SQLite, streams thumbnails and cached media
- one fetch worker thread — the only code that talks to Instagram, and the only writer of media and job rows

Not published externally; reachable only over the Compose network.

Running a single API process with a single worker thread is what makes "all Instagram-bound requests are serialized" structurally true rather than a convention that must be maintained.

### Volumes

| Container path | Host path | Contents |
|---|---|---|
| `/data/app.db` | `./data/app.db` | SQLite database, WAL mode |
| `/data/media/` | `./data/media/` | cached thumbnails and full-res media |
| `/data/session/` | `./data/session/` | Instaloader session file for the Instagram account |
| `/out/` | configurable (e.g. `~/Pictures/ig`) | destination for selected downloads |

The session directory is deliberately separate from the media cache so the cache can be cleared without invalidating the Instagram login.

### Media layout

```
/data/media/<username>/<shortcode>/
    thumb.jpg      # present after metadata fetch
    full.jpg       # or full.mp4 — single-item post, child_idx 0
    full_1.jpg     # carousel children, child_idx 1..N
    full_2.jpg
```

A single-item post has exactly one `full` row at `child_idx = 0` and the unsuffixed filename. A carousel has N `full` rows at `child_idx = 1..N` with suffixed filenames, and never a `child_idx = 0` row. A directory per shortcode gives carousel children an obvious home and makes clearing one profile a single `rm -rf`.

### Configuration

One `.env`:

| Variable | Purpose |
|---|---|
| `IG_USERNAME`, `IG_PASSWORD` | the dedicated Instagram account |
| `OUT_DIR` | host path bind-mounted to `/out` |
| `PAGE_SIZE` | posts fetched per `page_fetch` job (default 36) |
| `IG_MIN_INTERVAL` | seconds enforced between Instagram requests (default 3) |
| `IG_BACKOFF` | seconds the breaker holds after a 429 (default 900) |

## 3. Data model

SQLite in WAL mode. Five tables.

```sql
CREATE TABLE profiles (
  username        TEXT PRIMARY KEY,
  ig_user_id      TEXT,
  full_name       TEXT,
  biography       TEXT,
  is_private      INTEGER NOT NULL DEFAULT 0,
  post_count      INTEGER,
  avatar_path     TEXT,
  next_cursor     TEXT,              -- NodeIterator.freeze() JSON; NULL = not started, '' = exhausted
  tracked         INTEGER NOT NULL DEFAULT 0,
  last_synced_at  TEXT,
  created_at      TEXT NOT NULL
);

CREATE TABLE media_items (
  shortcode     TEXT PRIMARY KEY,
  username      TEXT NOT NULL REFERENCES profiles(username) ON DELETE CASCADE,
  kind          TEXT NOT NULL,        -- image | video | reel | carousel
  taken_at      TEXT NOT NULL,
  caption       TEXT,
  is_video      INTEGER NOT NULL,
  child_count   INTEGER NOT NULL DEFAULT 1,
  full_status   TEXT NOT NULL DEFAULT 'none',  -- none | queued | fetching | ready | failed
  full_error    TEXT,
  ig_url        TEXT NOT NULL,
  discovered_at TEXT NOT NULL
);
CREATE INDEX idx_media_profile ON media_items(username, taken_at DESC);

CREATE TABLE media_files (
  id         INTEGER PRIMARY KEY,
  shortcode  TEXT NOT NULL REFERENCES media_items(shortcode) ON DELETE CASCADE,
  role       TEXT NOT NULL,          -- thumb | full
  child_idx  INTEGER NOT NULL DEFAULT 0,
  path       TEXT NOT NULL,          -- relative to /data/media
  mime       TEXT,
  bytes      INTEGER,
  width      INTEGER,
  height     INTEGER,
  UNIQUE(shortcode, role, child_idx)
);

CREATE TABLE jobs (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,        -- profile_sync | page_fetch | media_fetch
  payload      TEXT NOT NULL,        -- JSON
  priority     INTEGER NOT NULL,     -- lower runs first
  status       TEXT NOT NULL,        -- queued | running | done | failed
  attempts     INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT
);
CREATE INDEX idx_jobs_pickup ON jobs(status, priority, created_at);

CREATE TABLE activity_log (
  id      INTEGER PRIMARY KEY,
  ts      TEXT NOT NULL,
  action  TEXT NOT NULL,             -- lookup | load_more | fetch_media | download | track | untrack
  target  TEXT,                      -- username or shortcode
  detail  TEXT                       -- JSON
);
CREATE INDEX idx_activity_ts ON activity_log(ts DESC);
```

Three decisions embedded in this schema:

**`media_files` handles thumbnails, full media, and carousel children uniformly.** A five-slide carousel is one `media_items` row, one thumb row, and five full rows. "Is this fully cached?" is `COUNT(full rows) == child_count`.

**`jobs.priority` exists because the user waits on some jobs and not others.** `media_fetch` (a download was clicked; a spinner is on screen) preempts `page_fetch` (background load-more). The same single worker runs both; only pickup order differs.

**No `downloads` table.** A download is one `activity_log` row whose `detail` is `{"base": "nike_ss26", "count": 12, "out": "/out/...", "shortcodes": [...]}`. With a single user there is nothing to reconcile, so a second table would only duplicate the log.

## 4. Fetch pipeline

### Worker loop

Started on FastAPI lifespan. Blocks on a `threading.Event` that HTTP handlers set when they enqueue a job. On wake it claims the lowest-`priority`, oldest `queued` row inside a transaction (`UPDATE jobs SET status='running' WHERE id = (SELECT ...)`), executes it, marks it terminal, and loops. An empty queue waits on the event with a 5-second timeout as a safety net. No polling storm; a second consumer is impossible by construction.

### Pacing

A subclass of `instaloader.RateController` enforces a floor between every Instagram-bound request (`IG_MIN_INTERVAL`, default 3s), layered on top of Instaloader's own 429 handling. Because exactly one thread issues these requests, that floor is a real global rate rather than a per-task intention.

### Session handling

On startup the worker loads `/data/session/<username>.session` if present, otherwise attempts `login()` using `.env` credentials. Two-factor prompts and checkpoint challenges cannot be solved headlessly, so an interactive entrypoint exists:

```
docker compose run api python -m app.ig.login
```

It performs the interactive login and writes the session file into the volume. All normal operation reuses that file.

### Job kinds

| Kind | Priority | Behaviour |
|---|---|---|
| `media_fetch` | 10 | one shortcode to full-res file(s) |
| `profile_sync` | 20 | `Profile.from_username`, upsert profile and avatar, enqueue first `page_fetch` |
| `page_fetch` | 30 | next N posts, upsert `media_items`, fetch thumbnails, save cursor |

`page_fetch` resumption uses Instaloader's `NodeIterator.freeze()` / `thaw()`, stored as JSON in `profiles.next_cursor`. This is the library's supported resume mechanism, so "Load more" continues the existing iterator rather than re-walking from the newest post.

### Quality

Full fetches pull `post.url` and `post.video_url` directly. These are the original assets; there is no transcode or resize step anywhere in the pipeline. Reels arrive as muxed MP4 with audio in the container, so no separate audio track needs reconciling. Thumbnails are the only derived asset and are never served as a download.

This satisfies PRD requirements 7 (maximum available quality) and 8 (Reels retain audio).

### Atomic writes

Every file is written as `<name>.part` and then moved into place with `os.replace()`. A container killed mid-fetch leaves `.part` litter and a row stuck at `full_status='fetching'`. Startup sweeps both: delete `.part` files, reset `fetching` rows to `none`.

### Failure taxonomy

- **Profile not found, or private** — terminal. Mark the profile, do not retry, report plainly in the UI. Private accounts are a stated PRD non-goal.
- **429 / rate limited** — trip a global circuit breaker. The worker sleeps for `IG_BACKOFF` (default 15 minutes) with the queue intact, and the UI shows a banner with the resume time. Retries are never spent against a throttle.
- **Login challenge or invalid session** — trip the breaker and keep it tripped. A human must run the login entrypoint. Automatic retry here is how a throttled account becomes a flagged one.
- **Transient network or 5xx** — retry with backoff, three attempts, then `failed` with the error text retained on the job row.

### Instaloader containment

The PRD correctly notes that Instagram rotates internal identifiers and breaks Instaloader every few weeks. Every `instaloader` import and call therefore lives in one module, `app/ig/adapter.py`, exposing four functions — `fetch_profile`, `fetch_page`, `fetch_media`, `login` — that return plain dataclasses. No other module in the codebase imports `instaloader`. A breakage has a blast radius of one file plus its contract tests. The version is pinned in `requirements.txt` and bumped deliberately.

### Downloads bypass the worker

Copying already-cached files into `/out/` is local I/O with no Instagram involvement, so it runs in the API threadpool. Only uncached selections enqueue `media_fetch` jobs. Selecting twenty already-cached posts completes in under a second and queues nothing.

## 5. API

```
GET    /api/status                        worker state, breaker (tripped/until/reason), queue depth
GET    /api/profiles                      tracked profiles
GET    /api/profiles/{u}                  profile row and sync state
POST   /api/profiles/{u}/sync             enqueue profile_sync (idempotent while one is queued)
PUT    /api/profiles/{u}/tracked          {tracked: bool}
DELETE /api/profiles/{u}/cache            remove cached media for a profile, retain rows
GET    /api/profiles/{u}/media?limit&offset   grid page, read directly from SQLite
POST   /api/profiles/{u}/load-more        enqueue page_fetch from the stored cursor

GET    /api/media/{sc}/thumb              stream thumbnail
GET    /api/media/{sc}/full?child=0       stream full-res, 404 unless ready
POST   /api/media/ensure                  {shortcodes[]} -> per-shortcode status, enqueues missing
POST   /api/downloads                     {shortcodes[], base} -> copies to /out, returns paths

GET    /api/activity?limit=100            log
GET    /api/health/canary                 live Instagram shape check
```

### Download flow

Three stateless calls, no new table:

1. `POST /api/media/ensure` with the selection. The server returns a per-shortcode status map (`ready` / `queued` / `fetching` / `failed`) and enqueues `media_fetch` for anything at `none`. Idempotent — repeat calls never double-enqueue.
2. The client re-polls the same endpoint every 1.5 seconds; it doubles as the progress feed.
3. Once everything is ready, `POST /api/downloads` copies cached files into `/out/`, named `{base}_01.jpg` … `{base}_12.mp4` — zero-padded, ordered by `taken_at`, carousel children suffixed `_01a`, `_01b`. One `activity_log` row is written and the resulting paths are returned.

**Known tradeoff:** the browser tab drives this flow, so closing it mid-wait stops progression. The in-flight `media_fetch` jobs still complete and remain cached, so reopening and re-selecting finishes immediately — nothing is lost beyond a repeated click. For a single-user local tool this is preferable to a downloads table plus a second assembler thread.

Polling rather than SSE or websockets: one user, a 1.5-second interval, three endpoints. Streaming infrastructure would be unjustified here.

## 6. Frontend

Three screens.

**Home** — username input, tracked-profile cards, recent-activity strip. Submitting an untracked username fires `sync` and routes to the profile screen in a loading state.

**Profile** — header with avatar, name, post count, last-synced time, track toggle, and clear-cache action. Below it, a responsive CSS grid of square thumbnails with badges for video, reel, and carousel count. Click to select, shift-click for a range, plus `Select all loaded`. A `Load more` control sits at the bottom, disabled once the cursor is exhausted.

When the selection is non-empty a sticky footer bar appears: selected count, base-filename input, and a `Download` button. That bar is the entire download interface — pressing it converts the bar into an inline progress row (`4 cached · 6 fetching · 2 queued`) and then a completion message naming the output directory.

**Activity** — reverse-chronological table rendering the log verbatim.

**Global banner**, rendered on every screen from `/api/status`. A tripped breaker shows either `Rate limited — resuming 14:32` or `Instagram session invalid — run the login command`. When Instaloader breaks, this banner is how the user finds out, instead of an unexplained empty grid.

## 7. Testing

The adapter boundary is what makes the system testable: four functions returning plain dataclasses, so everything above it tests against an in-memory fake with no network.

**Unit (no I/O)** — filename generation and zero-padding, carousel child naming, job pickup ordering, breaker state machine, `.part` sweep logic, cursor freeze/thaw round-trip.

**Worker (temp SQLite plus fake adapter)**

- the fake records call timestamps; assert no two Instagram calls ever overlap and every gap is at least `IG_MIN_INTERVAL`. This is the single property the whole design exists to guarantee, so it is tested directly.
- a `media_fetch` enqueued behind three `page_fetch` jobs runs first
- a fake raising 429 trips the breaker, leaves the queue intact, and resumes after backoff
- a fake raising a challenge error trips the breaker and keeps it tripped across retries
- killing the worker mid-fetch, then restarting, sweeps `.part` files and resets `fetching` rows

**API (TestClient, temp DB, fake adapter)** — `ensure` idempotency under repeated calls, `/full` returning 404 until ready, downloads writing correctly numbered files into a temporary `/out`, exactly one `activity_log` row per download.

**Live canary — opt-in, excluded from the normal run.** `pytest -m live` hits one known public profile and asserts shape: the profile resolves, a page returns items, and a media URL returns bytes. This is the test that reveals an Instagram-side rotation, and it is the only test permitted to touch the network. The same code backs `GET /api/health/canary`.

**No HTTP cassettes.** VCR-style recordings of Instaloader traffic would bake in session cookies and signed CDN URLs, and would keep passing for weeks after the real API changed — precisely the failure they would exist to catch. Parser tests use checked-in sample JSON payloads instead; the live canary covers the rest.

**Frontend** — one Playwright happy path against a seeded database and fake adapter: look up a profile, render the grid, select three items, set a base name, download, and assert three files land in a temporary output directory. Component-level tests are not worth their maintenance cost across three screens.

Development follows TDD throughout: tests precede implementation for each unit.

## 8. Observability

The worker emits structured JSON logs per job: job id, kind, target, duration, outcome. The `jobs` table is the operational history and `activity_log` is the user-facing one; both are queryable directly with `sqlite3` when something needs investigating.

## 9. Requirements traceability

| PRD req | Covered by |
|---|---|
| 1. Enter username, public only | `POST /api/profiles/{u}/sync`; private profiles terminate with a clear error |
| 2. Retrieve posts and Reels | `profile_sync` and `page_fetch` jobs; `media_items` |
| 3. Responsive media grid | Profile screen, CSS grid of thumbnails |
| 4. Select one, many, or all | Click, shift-click, `Select all loaded` |
| 5. Custom base filename | Base-filename input in the sticky footer bar; `POST /api/downloads` |
| 6. Individual files, not zipped | Files copied individually into `/out/` |
| 7. Maximum quality | Original `post.url` / `post.video_url`, no transcode or resize |
| 8. Reels retain audio | Muxed MP4 downloaded as-is |
| 9. Activity log | `activity_log` table, Activity screen |
| 10. Persistent tracked profiles | `profiles.tracked`, Home screen |
