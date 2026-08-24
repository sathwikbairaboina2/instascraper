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
and `fake` adapters, with each adapter keeping its own database and media
cache so neither dataset contaminates the other.

## Non-goals

- Switching to a third adapter. There are two.
- Migrating or merging data between the two roots.
- Editing `.env` from the UI. The toggle changes the running process and
  persists its own selection; nothing else about configuration is editable.
- Per-adapter breaker history. A switch clears the breaker; see "Breaker".

## Decisions taken during design

Recorded because each closed off a plausible alternative:

- **Separate data per adapter**, not a shared database and not a wipe on
  switch. Both datasets persist; switching is lossless.
- **Graph keeps the configured paths; fake nests beneath them.** Nothing
  that exists today moves, and Docker volume mounts are unchanged.
- **The selection persists across restarts**, with `IG_ADAPTER` acting as
  the first-run default rather than the permanent authority.
- **The control is always visible and asks for confirmation.** Seeing which
  dataset is live matters more than header tidiness; an accidental swap
  should be impossible.

## Alternatives considered and rejected

Both were specified in full before being set aside, so the reasoning is
recorded rather than reconstructed.

**A `source` column on shared tables.** One database, rows tagged
`graph`/`fake`. Rejected on failure mode rather than effort. Isolation
would become something every query has to remember instead of something
storage enforces: roughly 35 of the 52 statements grow a filter, and each
one missed is silent — fake rows surfacing in a real view, or a write
crossing sources — which is precisely the contamination this feature
exists to prevent, reintroduced as a bug class that no test catches unless
one is written per query. It also forces composite primary keys, because
the fake dataset seeds `nike` and `nike` is the obvious real target, so an
unchanged key means the second sync overwrites the first. SQLite cannot
alter a primary key in place, making that a rebuild of three tables against
existing data — the only irreversible step in the whole plan.

Its one real advantage: both datasets in a single file, so one backup
carries everything, and a future side-by-side view would be possible. That
did not outweigh the above.

**A second Compose profile.** `IG_ADAPTER=fake` with its own data volume,
started as a separate stack. Zero code, complete isolation, available
immediately. Rejected only because it delivers no in-app toggle and needs a
restart to switch. It remains the right answer if the toggle ever stops
earning its keep.

## Architecture

New module `api/app/runtime.py`, four small pieces with one job each.

### `Runtime`

```python
@dataclass(frozen=True)
class Runtime:
    name: str          # "graph" | "fake"
    settings: Settings
    adapter: object
```

Frozen on purpose. A swap replaces one immutable triple in a single
assignment, so there is no window in which the adapter is fake while the
paths still point at the real database. Two separate mutable fields would
have exactly that window, and the fake adapter would write into real data.

### `RuntimeConfig`

The holder. `.current` returns the live `Runtime`; `.swap(new)` replaces
it. It also retains `base` — the unmodified `load_settings()` result.

Retaining the base is a correctness requirement, not bookkeeping: deriving
fake paths from a runtime that is *already* fake would produce
`/data/fake/fake/app.db`. Every derivation starts from the base.

### `settings_for(base, name)`

Path derivation.

- `graph` returns `base` with `adapter="graph"`.
- `fake` returns a copy with `adapter="fake"` and each cache path rewritten
  as `p.parent / "fake" / p.name`:

  | Setting | graph | fake |
  |---|---|---|
  | `db_path` | `/data/app.db` | `/data/fake/app.db` |
  | `media_dir` | `/data/media` | `/data/fake/media` |
  | `out_dir` | `/out` | `/out` — **not** rewritten |

`out_dir` is your export folder, holding files you named and asked for. It
is not cache, so it is shared.

Because `settings_for` also sets `.adapter`, `make_adapter()` needs no
change: it still branches on `settings.adapter`.

### `read_selection(base)` / `write_selection(base, name)`

A one-line state file at `base.db_path.parent / "adapter.state"`, resolved
from the base so its location never depends on which adapter is active.

It is deliberately **not** a SQLite row. Each adapter has its own database,
so a selection stored in a database is circular — you cannot know which
database to open until you have read the selection. Making the graph
database a permanent control plane would mean opening real-data files
during a purely fake session.

`read_selection` falls back to `base.adapter` (i.e. `IG_ADAPTER`) when the
file is missing or its contents are not one of the two known names.

## Application wiring

`app.state.settings` and `app.state.adapter` are replaced by
`app.state.runtime`. Two sources of truth would drift the first time a new
call site forgot one. The eight existing readers are converted:

| File | Reads |
|---|---|
| `app/main_deps.py:13` | settings |
| `app/routes/downloads.py:20` | settings |
| `app/routes/media.py:28,49` | settings |
| `app/routes/profiles.py:98,167` | settings |
| `app/routes/status.py:14` | settings |
| `app/routes/health.py:38` | adapter |

`create_app(settings=..., adapter=..., start_worker=...)` keeps its exact
signature. `tests/conftest.py` and `tests/test_logging_json.py` inject both,
and an explicitly injected adapter pins the runtime rather than being
rebuilt from settings.

## Data flow

### Boot

1. `load_settings()` produces the base settings.
2. `read_selection(base)` yields the active name.
3. `settings_for(base, name)` yields the active settings.
4. `make_adapter(active)` yields the adapter.
5. `RuntimeConfig(base, Runtime(...))` is stored on `app.state.runtime`.
6. The lifespan hook prepares the active data root: `mkdir`, `init_schema`,
   `migrate`, `sweep`.
7. The worker starts, holding the holder.

### Switch — `POST /api/adapter`

Request body `{"adapter": "graph" | "fake"}`, matching the field name
`/status` already reports, so the same word means the same thing in both
directions.

1. An unrecognised name is a 400.
2. A name equal to the current one returns the current state unchanged, so
   the endpoint is idempotent.
3. Build the new settings and adapter.
4. Prepare the new data root: `mkdir`, `init_schema`, `migrate`, `sweep`.
5. Swap the runtime.
6. Clear the breaker.
7. Write the state file.
8. Return `{"adapter": name}`.

The ordering carries the failure semantics. Everything that can fail
happens before the swap; the swap itself is a single assignment and cannot
fail, and only after it do we mutate anything else. A failed switch
therefore leaves the process exactly where it was, with the breaker still
reflecting the adapter still in use. The state file is written last —
writing it earlier would let a crash in between persist a selection that
never took effect, and the next boot would come up in a state the user
never reached.

## Worker interaction

`Worker` takes the holder instead of a settings object and an adapter, and
resolves `self.runtime.current` once at the top of each job.

No coordination, locking or thread signalling is needed. `db.get_conn` is
keyed by path (see below), so the worker lands on the new database by
itself on its next job. A job already in flight completes against the root
it started on, which is coherent — it finishes writing where it began.

A consequence worth naming: the job queue is a table *inside* each
database, so queues are per-dataset automatically. Switching to fake does
not drain graph's pending work; it is still there on switching back.

## The `db.get_conn` fix

`db.get_conn()` caches one connection per thread and never re-checks
`db_path`. Nothing changes that path today, so the bug is latent — but the
moment it can change, the worker thread would keep writing to the old
database forever.

The thread-local cache becomes keyed by path: a request for a different
`db_path` closes the cached connection and opens the new one. This is a
correctness fix the feature depends on, not a refactor.

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

On success the handler navigates to `/` and reloads the page. Every piece
of data on screen came from a database that is no longer live, and a reload
is both simpler and more reliable than invalidating each cache and polling
hook by hand. `/` is also the correct destination rather than merely the
convenient one: the profile currently being viewed may not exist in the
other dataset.

## Testing

**`runtime.py`, pure and unit-tested:** graph settings pass through
unchanged; fake nests `db_path` and `media_dir`; `out_dir` is untouched;
deriving from the base twice never yields `fake/fake`. State file
round-trips, and falls back to `IG_ADAPTER` both when the file is absent
and when its contents are unrecognised.

**`db.get_conn` re-keying:** two different `db_path` values on one thread
yield different connections, and the superseded one is closed.

**Endpoint:** unknown name is a 400; the same name is idempotent; a switch
changes what `/status` reports; a write performed while on fake lands in
the nested database and not the base one; the breaker is cleared.

**Regression guard:** `tests/conftest.py` already injects `settings=` and
`adapter=` into `create_app`. The whole existing suite passing is the proof
that the signature and injection still work.

**e2e:** one new spec, deterministic and network-free. The suite runs on
fake; switching *to* graph with no token configured makes `GraphAdapter`
raise `IgChallenge` before any HTTP call, so the banner reads "Graph API
token not configured". That exercises control, confirmation, endpoint,
swap, reload and banner without touching the network.

To confirm during implementation rather than assume: `scripts/e2e-native.sh`
pins `DB_PATH` and `MEDIA_DIR` explicitly, so `seed_e2e.py` and the running
server must agree on the derived fake location. Both call the same
derivation, so they should — verify it.

## Success criteria

1. The header shows which dataset is live, and switching requires a
   confirmation.
2. Switching to fake shows the seeded dataset; switching back to graph
   shows the real one, unchanged and not re-synced.
3. Nothing written while on fake appears anywhere under the graph paths.
4. The selection survives an API restart; `IG_ADAPTER` applies only when no
   selection has ever been made.
5. A tripped breaker does not follow the user across a switch.
6. The full backend suite and all Playwright specs pass with no network
   access.
