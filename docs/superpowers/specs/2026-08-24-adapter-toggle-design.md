# Runtime adapter toggle — design

Date: 2026-08-24
Status: approved design, ready for an implementation plan
Branch: `feat/adapter-toggle`

## Why

The adapter is chosen once, at process start, from `IG_ADAPTER`. Switching
between the real Graph adapter and the fake one means editing `.env` and
restarting the stack. That is friction for demos, for screenshots, and for
checking whether a bug is in the UI or in the data.

## Goal

A control in the web UI that switches the running API between the `graph`
and `fake` adapters, with each adapter's data kept separate so neither
dataset contaminates the other.

## Non-goals

- Switching to a third adapter. There are two.
- Migrating or merging data between the two sources.
- Editing `.env` from the UI. The toggle changes the running process and
  persists its own selection; nothing else about configuration is editable.
- Per-source breaker history. A switch clears the breaker; see "Breaker".
- Viewing both datasets at once. Exactly one source is live at a time.

## Decisions taken during design

Recorded because each closed off a plausible alternative:

- **One database, rows tagged with a `source` column** — not separate
  database files, and not a wipe on switch. Both datasets persist and
  switching is lossless.
- **A flag column on the existing tables**, not parallel `fake_*` tables.
  One schema and one set of queries, each filtered, rather than a doubled
  schema whose every statement picks a table name at runtime.
- **The selection persists across restarts**, with `IG_ADAPTER` acting as
  the first-run default rather than the permanent authority.
- **The control is always visible and asks for confirmation.** Seeing which
  dataset is live matters more than header tidiness; an accidental swap
  should be impossible.

## Schema

This is the substance of the change. `source TEXT NOT NULL DEFAULT 'graph'`
is added to five tables, and the keys that need to distinguish datasets
become composite.

| Table | Today | Becomes |
|---|---|---|
| `profiles` | `PRIMARY KEY (username)` | `PRIMARY KEY (username, source)` |
| `media_items` | `PRIMARY KEY (shortcode)` | `PRIMARY KEY (shortcode, source)` |
| `media_files` | `UNIQUE(shortcode, role, child_idx)` | `UNIQUE(shortcode, source, role, child_idx)` |
| `jobs` | — | `source` column, no key change |
| `activity_log` | — | `source` column, no key change |

Composite keys are not optional here. The fake dataset seeds `nike`, and
`nike` is also the obvious real target, so the same username genuinely
exists in both datasets. With a plain `source` column and an unchanged
primary key, the second sync would overwrite the first.

Foreign keys follow: `media_items` references `profiles(username, source)`
and `media_files` references `media_items(shortcode, source)`. The index
`idx_media_profile` gains `source` as its leading column.

`jobs` carries `source` so that work enqueued while on fake is not executed
against graph after a switch. `activity_log` carries it so the activity
feed shows the dataset you are looking at.

## Migration

New installations get the new shape directly from `schema.sql`. Existing
databases need a rebuild, because **SQLite cannot alter a primary key in
place** — the existing `migrate()` helper only knows how to `ADD COLUMN`.

Detection is straightforward: if `PRAGMA table_info(profiles)` reports no
`source` column, the database predates this change.

The rebuild runs once, inside a single transaction with foreign keys
disabled, per affected table:

1. `CREATE TABLE <name>_new (...)` in the new shape.
2. `INSERT INTO <name>_new SELECT <columns>, 'graph' FROM <name>` — every
   existing row is real data by definition, so it is tagged `graph`.
3. `DROP TABLE <name>`, then `ALTER TABLE <name>_new RENAME TO <name>`.
4. Recreate the table's indexes.

Foreign keys are disabled for the duration and re-enabled after, so the
intermediate states where a child points at a dropped parent are not
rejected. Existing demo data survives, tagged `graph`.

## Media on disk

The flag separates rows; it cannot separate files. Media lives at
`media_dir/<username>/<shortcode>/thumb.jpg`, and the avatar at
`media_dir/<username>/avatar.jpg` — identical paths for fake `nike` and
real `nike`. Without intervention the two datasets would overwrite each
other's images while their rows stayed neatly separated.

So the media **root** is resolved per source: graph writes to `media_dir`
exactly as today, fake writes to `media_dir/fake`. Nothing that exists
moves, and Docker volume mounts are unchanged.

One helper, `media_root(settings, source)`, is the only new concept.
Because `media_files.path` is already stored *relative to* `media_dir`, a
fake row naturally records `fake/nike/.../thumb.jpg`, and the media-serving
routes join it against `media_dir` and work unchanged. `out_dir` is not
scoped: downloads are your export folder, holding files you named, not
cache.

## Runtime holder

Settings no longer vary between sources — only the adapter and the source
name do. So this stays small:

```python
@dataclass(frozen=True)
class Runtime:
    name: str      # "graph" | "fake"
    adapter: object
```

`RuntimeConfig` holds one `Runtime`, exposes `.current`, and `.swap(new)`
replaces it. `app.state.runtime` is added; `app.state.settings` stays
exactly as it is, since settings are now constant for the process lifetime.

`Worker` takes the holder instead of a bare adapter and resolves
`self.runtime.current` once at the top of each job. This is required
because `Worker` caches `self.adapter` today (`runner.py:45`): reassigning
`app.state.adapter` would change what the routes see while the worker
thread kept using the old one, and the toggle would appear to work while
doing nothing.

A job already in flight completes against the source it started on, which
is coherent — it finishes writing where it began.

`create_app(settings=..., adapter=..., start_worker=...)` keeps its exact
signature; `tests/conftest.py` and `tests/test_logging_json.py` inject both,
and an injected adapter pins the runtime.

## Threading the source through queries

52 SQL statements live across seven files. That is the surface to audit,
not the count to change — statements reading unscoped tables, and `sweep`
(see below), stay as they are.

| File | Statements |
|---|---|
| `app/worker/handlers.py` | 16 |
| `app/routes/profiles.py` | 14 |
| `app/worker/queue.py` | 11 |
| `app/routes/media.py` | 4 |
| `app/services/downloads.py` | 3 |
| `app/worker/sweep.py` | 2 |
| `app/services/activity.py` | 2 |

The source reaches them by the same route the connection already does:

- **Routes** read `request.app.state.runtime.current.name`.
- **Handlers** read `ctx.source`; `HandlerContext` gains the field, set by
  the worker from the runtime it resolved for that job.
- **Queue** takes source on `enqueue`, and filters on claim, so a worker
  only ever picks up work belonging to the live source.
- **Sweep stays source-agnostic, deliberately.** It resets rows stuck in
  `fetching`/`queued` and jobs stuck in `running`, and it runs once at
  startup — at which point nothing is in flight for *either* source, so
  resetting both is the correct recovery rather than an oversight. Its
  `*.part` cleanup walks `media_dir` recursively and therefore reaches
  fake's files for free, since fake nests inside. Neither of its two
  statements is scoped.

## Selection persistence

With a single database this is no longer circular, so it is simply a row.
A small `app_state (key TEXT PRIMARY KEY, value TEXT)` table stores
`adapter`. It is read at boot, after schema init and migration, and written
on each successful switch. `IG_ADAPTER` applies only when no row exists.

`app_state` needs no migration of its own. `init_schema` runs `schema.sql`
on every boot and every statement there is `CREATE TABLE IF NOT EXISTS`, so
an existing database gains the table the first time it starts on this
version.

## Switch — `POST /api/adapter`

Request body `{"adapter": "graph" | "fake"}`, matching the field name
`/status` already reports, so the same word means the same thing in both
directions.

1. An unrecognised name is a 400.
2. A name equal to the current one returns the current state unchanged, so
   the endpoint is idempotent.
3. Build the new adapter.
4. Ensure the new source's media root exists.
5. Swap the runtime.
6. Clear the breaker.
7. Persist the selection.
8. Return `{"adapter": name}`.

Everything that can fail happens before the swap; the swap itself is a
single assignment and cannot fail, and only after it does anything else
mutate. A failed switch therefore leaves the process exactly where it was,
with the breaker still reflecting the adapter still in use. The selection
is persisted last, so a crash midway cannot record a choice that never took
effect and strand the next boot in a state the user never reached.

## Breaker

The breaker is process-wide. Without intervention, a graph session that
trips it permanently on a dead token would hand a tripped breaker to a fake
session, the worker would refuse to run, and the toggle would appear
broken.

So a switch clears the breaker. Nothing is lost: if the token really is
dead, the next graph call trips it again immediately.

## Frontend

`StatusBody` gains `adapter: 'graph' | 'fake'`, and `api.ts` gains
`setAdapter(name)`.

`AppShell` renders an Ant Design `Segmented` control in the header showing
the live dataset, wrapped in a `Popconfirm`. The confirmation text states
that the app will reload and that the other dataset is kept, not deleted.

On success the handler navigates to `/` and reloads. Every piece of data on
screen came from a source that is no longer live, and a reload is both
simpler and more reliable than invalidating each cache and polling hook by
hand. `/` is also the correct destination rather than the convenient one:
the profile being viewed may not exist in the other dataset.

## Testing

**Migration, the highest-risk piece.** Build a database in the old shape,
populate it, migrate, and assert: every pre-existing row is tagged `graph`,
nothing was lost, the new keys and indexes exist, and running the migration
twice is a no-op.

**Isolation, the property that matters.** Sync `nike` under both sources
and assert two distinct profile rows coexist, that each source's queries
return only its own rows, and that fake media files land under
`media_dir/fake` while graph's stay at the top level.

**Queue scoping.** A job enqueued while on fake is not claimed by a worker
running as graph.

**Endpoint.** Unknown name is a 400; the same name is idempotent; a switch
changes what `/status` reports; the breaker is cleared.

**Regression guard.** `tests/conftest.py` already injects `settings=` and
`adapter=` into `create_app`, and the existing suite covers the unscoped
behaviour. That suite passing unchanged — with every query now carrying a
source — is the proof that scoping did not alter single-source behaviour.

**e2e:** one new spec, deterministic and network-free. The suite runs on
fake; switching *to* graph with no token configured makes `GraphAdapter`
raise `IgChallenge` before any HTTP call, so the banner reads "Graph API
token not configured". That exercises control, confirmation, endpoint,
swap, reload and banner without touching the network.

## Success criteria

1. The header shows which dataset is live, and switching requires a
   confirmation.
2. Switching to fake shows the seeded dataset; switching back to graph
   shows the real one, unchanged and not re-synced.
3. The same username can exist under both sources without either
   overwriting the other, in the database and on disk.
4. Work queued under one source is never executed under the other.
5. The selection survives an API restart; `IG_ADAPTER` applies only when no
   selection has ever been made.
6. An existing database migrates with every row preserved and tagged
   `graph`.
7. A tripped breaker does not follow the user across a switch.
8. The full backend suite and all Playwright specs pass with no network
   access.
