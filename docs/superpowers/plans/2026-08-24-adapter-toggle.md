# Runtime Adapter Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A confirmed control in the web header that switches the running API between the `graph` and `fake` adapters, each keeping its own database and media cache.

**Architecture:** A `RuntimeConfig` holder carries one immutable `Runtime(name, settings, adapter)` triple. Routes and the worker resolve through the holder, so a switch is a single assignment that can never leave the fake adapter pointed at real data. Fake's cache paths are derived by nesting under `fake/`, so isolation is enforced by the filesystem and **not one existing SQL statement changes**.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Next.js 15, Ant Design 6, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-adapter-toggle-design.md`

## Global Constraints

- **Interpreter:** the system `python` has no pytest. Every `python` in this plan means `C:/Users/sathwik/projects/instascraper/.venv/Scripts/python.exe`. Run test commands from `api/` with an absolute interpreter path.
- **Baseline before Task 1:** 203 passed, 4 skipped, 36 e2e specs.
- **No SQL statement changes.** If a task finds itself editing a query, the design has been misread — isolation is by database file, not by row.
- **`graph` keeps the configured paths; `fake` nests beneath them.** `db_path` `/data/app.db` → `/data/fake/app.db`; `media_dir` `/data/media` → `/data/fake/media`.
- **`out_dir` is never rewritten.** Downloads are the user's export folder, not cache.
- **Every derivation starts from the pristine base settings**, never from the current runtime, or fake derived twice yields `fake/fake`.
- **The selection is a state file, not a SQLite row** — each adapter has its own database, so storing it in one is circular.
- Adapter names are exactly `"graph"` and `"fake"`.
- Work happens on branch `feat/adapter-toggle`.

---

### Task 1: Key the thread-local connection by path

`db.get_conn()` caches one connection per thread and never re-checks `db_path`. Harmless today because nothing changes that path — this feature is what activates it, and without the fix the worker thread would keep writing to the old database forever after a switch, silently. Foundation for everything else.

**Files:**
- Modify: `api/app/db.py:31-38` (`get_conn`), `:40-44` (`reset_thread_state`)
- Test: `api/tests/test_db_threading.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `db.get_conn(settings)` returning a connection bound to `settings.db_path`, closing and replacing the cached one when the path differs.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_db_threading.py`:

```python
def test_get_conn_follows_a_changed_db_path(settings, tmp_path):
    """The worker thread must not keep writing to the old database."""
    from dataclasses import replace

    first = db.get_conn(settings)
    db.init_schema(first)

    other = replace(settings, db_path=tmp_path / "other" / "app.db")
    second = db.get_conn(other)

    assert second is not first
    # The superseded connection is closed, not leaked.
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")

    db.reset_thread_state()


def test_get_conn_reuses_the_connection_for_the_same_path(settings):
    first = db.get_conn(settings)
    assert db.get_conn(settings) is first
    db.reset_thread_state()
```

Ensure the file imports `sqlite3` and `pytest` at the top; add whichever is missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_db_threading.py -k changed_db_path -v`
Expected: FAIL — `second is first`, because the cache ignores the path.

- [ ] **Step 3: Write minimal implementation**

Replace `get_conn` and `reset_thread_state` in `api/app/db.py`:

```python
def get_conn(settings: Settings) -> sqlite3.Connection:
    """Long-lived connection cached per thread. Used by the worker thread.

    Keyed by path: the adapter toggle changes db_path at runtime, and a
    cache that ignored it would keep the worker writing to the database it
    started with.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        if getattr(_local, "conn_path", None) == settings.db_path:
            return conn
        conn.close()
    conn = _connect(settings.db_path)
    _local.conn = conn
    _local.conn_path = settings.db_path
    return conn


def reset_thread_state() -> None:
    """Test helper: forget this thread's cached connection."""
    if getattr(_local, "conn", None) is not None:
        _local.conn = None
    _local.conn_path = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS — 205 passed, 4 skipped.

- [ ] **Step 5: Commit**

```bash
git add api/app/db.py api/tests/test_db_threading.py
git commit -m "fix(api): key the thread-local connection by database path"
```

---

### Task 2: The runtime triple and path derivation

The pure half of `runtime.py`: no I/O, no app state.

**Files:**
- Create: `api/app/runtime.py`
- Test: `api/tests/test_runtime.py`

**Interfaces:**
- Consumes: `Settings` from `app.config`.
- Produces: `NAMES = ("graph", "fake")`; `Runtime(name: str, settings: Settings, adapter: object)` frozen; `settings_for(base: Settings, name: str) -> Settings`; `RuntimeConfig(base, current)` with `.base`, `.current`, `.swap(new)` and classmethod `.fixed(settings, adapter, name="fake")`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_runtime.py`:

```python
from dataclasses import replace
from pathlib import Path

import pytest

from app import runtime


def test_graph_keeps_the_configured_paths(settings):
    active = runtime.settings_for(settings, "graph")
    assert active.db_path == settings.db_path
    assert active.media_dir == settings.media_dir
    assert active.adapter == "graph"


def test_fake_nests_the_cache_paths(settings):
    base = replace(
        settings, db_path=Path("/data/app.db"), media_dir=Path("/data/media")
    )
    active = runtime.settings_for(base, "fake")
    assert active.db_path == Path("/data/fake/app.db")
    assert active.media_dir == Path("/data/fake/media")
    assert active.adapter == "fake"


def test_out_dir_is_never_nested(settings):
    """Downloads are the user's export folder, not cache."""
    active = runtime.settings_for(settings, "fake")
    assert active.out_dir == settings.out_dir


def test_deriving_from_the_base_twice_never_double_nests(settings):
    base = replace(settings, db_path=Path("/data/app.db"))
    once = runtime.settings_for(base, "fake")
    twice = runtime.settings_for(base, "fake")
    assert once.db_path == twice.db_path == Path("/data/fake/app.db")


def test_unknown_name_is_rejected(settings):
    with pytest.raises(ValueError):
        runtime.settings_for(settings, "instaloader")


def test_holder_swaps_the_whole_triple(settings):
    first = runtime.Runtime("graph", settings, adapter="A")
    second = runtime.Runtime("fake", settings, adapter="B")
    holder = runtime.RuntimeConfig(settings, first)

    assert holder.current is first
    holder.swap(second)
    assert holder.current is second
    assert holder.current.name == "fake"
    assert holder.current.adapter == "B"


def test_holder_retains_the_pristine_base(settings):
    """Switches derive from base, never from the already-derived current."""
    fake = runtime.settings_for(settings, "fake")
    holder = runtime.RuntimeConfig(settings, runtime.Runtime("fake", fake, "A"))
    assert holder.base.db_path == settings.db_path


def test_fixed_holder_helper(settings):
    holder = runtime.RuntimeConfig.fixed(settings, adapter="A")
    assert holder.current.name == "fake"
    assert holder.current.adapter == "A"
    assert holder.base is settings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_runtime.py -v`
Expected: FAIL with `ImportError: cannot import name 'runtime' from 'app'`

- [ ] **Step 3: Write minimal implementation**

Create `api/app/runtime.py`:

```python
"""Which adapter is live, and where its data lives.

The adapter can change while the process runs, and each adapter keeps its
own database and media cache. Isolation is therefore enforced by the
filesystem rather than by every query remembering to filter.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from app.config import Settings

NAMES = ("graph", "fake")


@dataclass(frozen=True)
class Runtime:
    """The live adapter and the settings that point at its data.

    Frozen so a switch replaces one triple in a single assignment. Two
    mutable fields would leave a window in which the adapter is already
    fake while the paths still address the real database.
    """

    name: str
    settings: Settings
    adapter: object


def _nest(path: Path) -> Path:
    return path.parent / "fake" / path.name


def settings_for(base: Settings, name: str) -> Settings:
    """Derive the settings for one adapter. Always call with the base."""
    if name not in NAMES:
        raise ValueError(f"unknown adapter {name!r}")
    if name == "graph":
        return replace(base, adapter="graph")
    # out_dir is deliberately untouched: it holds files the user named.
    return replace(
        base,
        adapter="fake",
        db_path=_nest(base.db_path),
        media_dir=_nest(base.media_dir),
    )


class RuntimeConfig:
    """Holds the live Runtime and the base settings every switch derives from."""

    def __init__(self, base: Settings, current: Runtime):
        self.base = base
        self._current = current

    @property
    def current(self) -> Runtime:
        return self._current

    def swap(self, new: Runtime) -> None:
        self._current = new

    @classmethod
    def fixed(cls, settings: Settings, adapter, name: str = "fake") -> "RuntimeConfig":
        """Test helper: a holder pinned to one adapter."""
        return cls(settings, Runtime(name, settings, adapter))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/runtime.py api/tests/test_runtime.py
git commit -m "feat(api): add the runtime triple and per-adapter path derivation"
```

---

### Task 3: Selection persistence and data-root preparation

The I/O half of `runtime.py`: the state file that survives a restart, and the routine that makes a data root usable.

**Files:**
- Modify: `api/app/runtime.py`
- Test: `api/tests/test_runtime.py`

**Interfaces:**
- Consumes: `settings_for` from Task 2, `db.init_schema` / `db.migrate` / `db.new_conn`, `sweep.sweep`.
- Produces: `state_path(base) -> Path`; `read_selection(base) -> str`; `write_selection(base, name) -> None`; `prepare_data_root(settings) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_runtime.py`:

```python
def test_selection_round_trips(settings):
    runtime.write_selection(settings, "fake")
    assert runtime.read_selection(settings) == "fake"


def test_missing_state_file_falls_back_to_the_env_default(settings):
    base = replace(settings, adapter="graph")
    assert not runtime.state_path(base).exists()
    assert runtime.read_selection(base) == "graph"


def test_unrecognised_state_file_falls_back_to_the_env_default(settings):
    base = replace(settings, adapter="graph")
    path = runtime.state_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("instaloader", encoding="utf-8")
    assert runtime.read_selection(base) == "graph"


def test_state_file_location_does_not_depend_on_the_active_adapter(settings):
    """It is resolved from the base, so fake and graph agree on where it is."""
    fake = runtime.settings_for(settings, "fake")
    assert runtime.state_path(settings) != runtime.state_path(fake)
    # ...which is exactly why callers must pass the base, never the derived.
    runtime.write_selection(settings, "fake")
    assert runtime.read_selection(settings) == "fake"


def test_prepare_data_root_creates_a_usable_database(settings):
    target = runtime.settings_for(settings, "fake")
    runtime.prepare_data_root(target)

    assert target.db_path.exists()
    assert target.media_dir.exists()

    conn = db.new_conn(target)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert {"profiles", "media_items", "media_files", "jobs"} <= tables


def test_prepare_data_root_is_idempotent(settings):
    target = runtime.settings_for(settings, "fake")
    runtime.prepare_data_root(target)
    runtime.prepare_data_root(target)
    assert target.db_path.exists()
```

Add `from app import db` to the imports at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_runtime.py -k "selection or state_file or prepare" -v`
Expected: FAIL with `AttributeError: module 'app.runtime' has no attribute 'write_selection'`

- [ ] **Step 3: Write minimal implementation**

Append to `api/app/runtime.py`:

```python
from app import db
from app.worker import sweep as sweep_module

_STATE_FILE = "adapter.state"


def state_path(base: Settings) -> Path:
    """Where the selection lives. Always resolved from the base settings.

    Not a SQLite row: each adapter has its own database, so a selection
    stored in one is circular -- you cannot know which database to open
    until you have read the selection.
    """
    return base.db_path.parent / _STATE_FILE


def read_selection(base: Settings) -> str:
    try:
        name = state_path(base).read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if name in NAMES:
        return name
    return base.adapter if base.adapter in NAMES else "graph"


def write_selection(base: Settings, name: str) -> None:
    path = state_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name, encoding="utf-8")


def prepare_data_root(settings: Settings) -> dict:
    """Make a data root usable: directories, schema, migration, recovery."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    for directory in (settings.media_dir, settings.out_dir):
        directory.mkdir(parents=True, exist_ok=True)

    conn = db.new_conn(settings)
    try:
        db.init_schema(conn)
        db.migrate(conn)
        return sweep_module.sweep(conn, settings.media_dir)
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/test_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/runtime.py api/tests/test_runtime.py
git commit -m "feat(api): persist the adapter selection and prepare data roots"
```

---

### Task 4: Wire the app to the runtime holder

Replaces `app.state.settings` and `app.state.adapter` with `app.state.runtime`, and converts the eight readers. Two sources of truth would drift the first time a new call site forgot one.

**Files:**
- Modify: `api/app/main.py:25-76`, `api/app/main_deps.py:13`, `api/app/routes/downloads.py:20`, `api/app/routes/media.py:28,49`, `api/app/routes/profiles.py:98,167`, `api/app/routes/status.py:14`, `api/app/routes/health.py:38`
- Test: `api/tests/test_api_status.py`

**Interfaces:**
- Consumes: `RuntimeConfig`, `Runtime`, `settings_for`, `read_selection`, `prepare_data_root` from Tasks 2-3.
- Produces: `app.state.runtime` (a `RuntimeConfig`). Every route reads `request.app.state.runtime.current.settings` or `.adapter`. `create_app(settings=..., adapter=..., start_worker=...)` keeps its exact signature.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_api_status.py`:

```python
def test_status_reports_the_live_adapter(client):
    body = client.get("/api/status").json()
    assert body["adapter"] == "fake"


def test_app_exposes_a_runtime_holder(client):
    holder = client.app_state.runtime
    assert holder.current.name == "fake"
    assert holder.base is not None


def test_injected_adapter_pins_the_runtime(settings):
    """conftest injects an adapter; it must not be rebuilt from settings."""
    from app.ig.fake import FakeAdapter
    from app.main import create_app

    injected = FakeAdapter()
    app = create_app(settings=settings, adapter=injected, start_worker=False)
    assert app.state.runtime.current.adapter is injected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_api_status.py -k "adapter or runtime" -v`
Expected: FAIL — `/status` has no `adapter` key and `app.state` has no `runtime`.

- [ ] **Step 3: Write minimal implementation**

In `api/app/main.py`, replace the body of `create_app` down to the `app.state` assignments:

```python
def create_app(
    settings: Settings | None = None,
    adapter=None,
    start_worker: bool = True,
) -> FastAPI:
    base = settings or load_settings()
    name = base.adapter if adapter is not None else runtime.read_selection(base)
    active = runtime.settings_for(base, name) if adapter is None else base
    holder = runtime.RuntimeConfig(base, runtime.Runtime(name, active, adapter or make_adapter(active)))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = app.state.runtime.current
        result = runtime.prepare_data_root(current.settings)
        # json.dumps, not %s: a dict interpolated into a string emits Python
        # repr with single quotes, which is not parseable JSON.
        logging.info(json.dumps({"event": "sweep", **result}))

        if start_worker:
            worker = Worker(
                settings=current.settings,
                adapter=current.adapter,
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
    app.state.runtime = holder
    app.state.breaker = Breaker()
    app.state.pacer = Pacer(min_interval=base.ig_min_interval)
    app.state.worker = None
```

Delete the `app.state.settings` and `app.state.adapter` lines. Add `from app import runtime` to the imports. Remove the now-unused `db` import only if nothing else in the file uses it — `db.get_conn` was called in the old lifespan and is no longer needed there.

Convert the eight readers. In `api/app/main_deps.py`:

```python
    conn = db.new_conn(request.app.state.runtime.current.settings)
```

In `api/app/routes/downloads.py:20`:

```python
        return downloads.run(
            conn, request.app.state.runtime.current.settings, body.shortcodes, body.base
        )
```

In `api/app/routes/media.py`, both line 28 and line 49:

```python
    path = request.app.state.runtime.current.settings.media_dir / row["path"]
```

In `api/app/routes/profiles.py:98`:

```python
    path = request.app.state.runtime.current.settings.media_dir / row["avatar_path"]
```

and `:167`:

```python
    media_root = request.app.state.runtime.current.settings.media_dir
```

In `api/app/routes/health.py:38`:

```python
        return run_canary(request.app.state.runtime.current.adapter, username, Path(tmp))
```

In `api/app/routes/status.py`, replace the whole return:

```python
@router.get("/status")
def get_status(request: Request, conn=Depends(get_conn_dep)):
    worker = getattr(request.app.state, "worker", None)
    current = request.app.state.runtime.current
    return {
        "worker": "running" if worker is not None and worker.is_alive() else "stopped",
        "adapter": current.name,
        "token_configured": bool(current.settings.graph_token),
        "breaker": request.app.state.breaker.state(),
        "queue_depth": queue.depth(conn),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS — the whole suite, since `create_app`'s signature is unchanged.

- [ ] **Step 5: Commit**

```bash
git add api/app/main.py api/app/main_deps.py api/app/routes/ api/tests/test_api_status.py
git commit -m "feat(api): resolve settings and adapter through a runtime holder"
```

---

### Task 5: The worker resolves through the holder

`Worker` caches `self.adapter` and `self.settings` today. Reassigning the holder's contents would change what the routes see while the worker thread kept using the old values — the toggle would appear to work and silently do nothing.

**Files:**
- Modify: `api/app/worker/runner.py:35-52` (`__init__`), `:58-60` (`drain`), `:69-84` (`run`), `:85-100` (`_run_job`); `api/app/main.py` (worker construction)
- Test: `api/tests/test_worker_runner.py`, `api/tests/test_backoff_respect.py`

**Interfaces:**
- Consumes: `RuntimeConfig` from Task 2.
- Produces: `Worker(runtime, breaker, pacer, handlers)` — `settings` and `adapter` are no longer constructor arguments. `HandlerContext` is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_worker_runner.py`:

```python
def test_worker_picks_up_a_swapped_adapter_on_the_next_job(worker_env):
    """A cached adapter reference would make the toggle silently do nothing."""
    from app import runtime as rt
    from app.ig.fake import FakeAdapter
    from app.worker.runner import Worker

    settings, conn, adapter, breaker, pacer = worker_env
    first, second = FakeAdapter(), FakeAdapter()
    holder = rt.RuntimeConfig(settings, rt.Runtime("fake", settings, first))

    seen = []

    def handler(ctx, payload):
        seen.append(ctx.adapter)

    queue.enqueue(conn, "profile_sync", {"username": "nike"})
    worker = Worker(holder, breaker, pacer, {"profile_sync": handler})
    worker.start()
    worker.wake.set()
    worker.drain(timeout=2.0)

    holder.swap(rt.Runtime("graph", settings, second))
    queue.enqueue(conn, "profile_sync", {"username": "adidas"})
    worker.wake.set()
    worker.drain(timeout=2.0)
    worker.shutdown()

    assert seen == [first, second], "worker kept using the adapter it started with"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_worker_runner.py -k swapped -v`
Expected: FAIL with `TypeError` — `Worker` still takes `settings` and `adapter` positionally.

- [ ] **Step 3: Write minimal implementation**

In `api/app/worker/runner.py`, replace the constructor:

```python
    def __init__(
        self,
        runtime,
        breaker: Breaker,
        pacer: Pacer,
        handlers: dict[str, Handler],
    ):
        super().__init__(name="ig-worker", daemon=True)
        self.runtime = runtime
        self.breaker = breaker
        self.pacer = pacer
        self.handlers = handlers
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
```

In `drain`, resolve through the holder:

```python
        conn = db.get_conn(self.runtime.current.settings)
```

Replace `run` so both the settings and the adapter are resolved per iteration — the database may have changed too, and `db.get_conn` is now keyed by path:

```python
    def run(self) -> None:
        while not self.stop_flag.is_set():
            current = self.runtime.current
            conn = db.get_conn(current.settings)

            wait = self.breaker.wait_seconds()
            if wait > 0:
                self.stop_flag.wait(min(wait, IDLE_TIMEOUT))
                continue

            job = queue.claim_next(conn)
            if job is None:
                self.wake.wait(IDLE_TIMEOUT)
                self.wake.clear()
                continue

            self._run_job(conn, current, job)
```

Change `_run_job` to take the resolved runtime and build the context from it. Replace its signature and the `HandlerContext` construction:

```python
    def _run_job(self, conn, current, job) -> None:
        payload = json.loads(job["payload"])
        handler = self.handlers.get(job["kind"])
        started = time.monotonic()

        if handler is None:
            queue.fail(conn, job["id"], f"no handler for {job['kind']}", retryable=False)
            return

        ctx = HandlerContext(
            conn=conn,
            adapter=current.adapter,
            settings=current.settings,
            pacer=self.pacer,
            enqueue=lambda kind, p: self._enqueue(conn, kind, p),
        )
```

Catch any remaining references — `grep -n "self\.settings\|self\.adapter" app/worker/runner.py` should return nothing when this task is done.

In `api/app/main.py`, construct the worker from the holder:

```python
            worker = Worker(
                app.state.runtime,
                app.state.breaker,
                app.state.pacer,
                HANDLERS,
            )
```

Existing tests construct `Worker` directly. In `api/tests/test_backoff_respect.py` there are three such calls, all of the form `Worker(s, FakeAdapter(), breaker, Pacer(0.0), {...})` or `Worker(settings, FakeAdapter(), ...)`. Convert each using the test helper:

```python
    worker = Worker(
        RuntimeConfig.fixed(s, FakeAdapter()), breaker, Pacer(0.0), {"profile_sync": handler}
    )
```

adding `from app.runtime import RuntimeConfig` to the file. Apply the same conversion to the `_run` helper in `api/tests/test_worker_runner.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/worker/runner.py api/app/main.py api/tests/test_worker_runner.py api/tests/test_backoff_respect.py
git commit -m "feat(api): resolve the adapter per job instead of caching it"
```

---

### Task 6: The switch endpoint

**Files:**
- Modify: `api/app/routes/status.py`
- Test: `api/tests/test_api_status.py`

**Interfaces:**
- Consumes: everything from Tasks 2-5.
- Produces: `POST /api/adapter` accepting `{"adapter": "graph" | "fake"}` and returning `{"adapter": name}`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_api_status.py`:

```python
def test_switching_changes_what_status_reports(client):
    assert client.post("/api/adapter", json={"adapter": "graph"}).status_code == 200
    assert client.get("/api/status").json()["adapter"] == "graph"


def test_switching_is_idempotent(client):
    body = client.post("/api/adapter", json={"adapter": "fake"}).json()
    assert body["adapter"] == "fake"


def test_unknown_adapter_is_rejected(client):
    assert client.post("/api/adapter", json={"adapter": "instaloader"}).status_code == 400


def test_switching_clears_the_breaker(client):
    client.app_state.breaker.trip_permanent("Instagram token invalid: checkpoint")
    assert client.app_state.breaker.state()["tripped"] is True

    client.post("/api/adapter", json={"adapter": "graph"})

    assert client.app_state.breaker.state()["tripped"] is False


def test_switching_persists_the_selection(client, settings):
    from app import runtime

    client.post("/api/adapter", json={"adapter": "graph"})
    assert runtime.read_selection(settings) == "graph"


def test_fake_data_never_reaches_the_graph_root(settings):
    """The isolation the whole feature exists for.

    Built without an injected adapter, so paths are genuinely derived --
    the `client` fixture injects one, which deliberately pins the runtime
    to the base paths and would make this assertion vacuous.
    """
    from dataclasses import replace

    from app import runtime
    from app.main import create_app

    base = replace(settings, adapter="fake", graph_token="", graph_user_id="")
    app = create_app(settings=base, start_worker=False)

    active = app.state.runtime.current.settings
    assert active.db_path == base.db_path.parent / "fake" / base.db_path.name
    assert active.media_dir == base.media_dir.parent / "fake" / base.media_dir.name
    # The export folder is shared on purpose: it holds files the user named.
    assert active.out_dir == base.out_dir

    runtime.prepare_data_root(active)
    assert active.db_path.exists()
    assert not base.db_path.exists(), "fake wrote into the graph root"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/test_api_status.py -k "switching or unknown_adapter" -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Write minimal implementation**

In `api/app/routes/status.py`, add the imports and the route:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import runtime as rt
from app.ig.factory import make_adapter
from app.main_deps import get_conn_dep
from app.worker import queue


class AdapterBody(BaseModel):
    adapter: str


@router.post("/adapter")
def set_adapter(request: Request, body: AdapterBody):
    """Switch the live adapter, and with it the data root it reads and writes."""
    holder = request.app.state.runtime
    name = body.adapter
    if name not in rt.NAMES:
        raise HTTPException(status_code=400, detail=f"unknown adapter {name!r}")
    if name == holder.current.name:
        return {"adapter": name}

    # Everything that can fail happens before the swap, so a failed switch
    # leaves the process exactly where it was.
    settings = rt.settings_for(holder.base, name)
    adapter = make_adapter(settings)
    rt.prepare_data_root(settings)

    holder.swap(rt.Runtime(name, settings, adapter))
    request.app.state.breaker.clear()
    # Persisted last: a crash before this must not record a choice that
    # never took effect.
    rt.write_selection(holder.base, name)
    return {"adapter": name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/routes/status.py api/tests/test_api_status.py
git commit -m "feat(api): add an endpoint that switches the live adapter"
```

---

### Task 7: The header control

**Files:**
- Modify: `web/lib/api.ts:1-11` (`StatusBody`), end of file (new function); `web/components/AppShell.tsx` (imports, header strip)
- Test: covered by Task 8's e2e spec; `npx tsc --noEmit` is this task's gate.

**Interfaces:**
- Consumes: `POST /api/adapter` from Task 6.
- Produces: `StatusBody.adapter: 'graph' | 'fake'`; `setAdapter(adapter: 'graph' | 'fake')`.

**On the missing red step.** There is no failing-test-first cycle here, and
inventing one would be theatre: adding a field to a read-only type and a new
`export const` is type-safe by construction, so `tsc` cannot fail on it. The
behavioural gate for this task is Task 8's e2e spec, which is written against
this control and does fail without it. Keep the two tasks adjacent.

- [ ] **Step 1: Extend the API client**

Add to `web/lib/api.ts`, inside `StatusBody` after `worker`:

```ts
  adapter: 'graph' | 'fake'
```

and at the end of the file, matching the existing `export const` style:

```ts
export const setAdapter = (adapter: 'graph' | 'fake') =>
  call<{ adapter: 'graph' | 'fake' }>('/api/adapter', {
    method: 'POST',
    body: JSON.stringify({ adapter }),
  })
```

- [ ] **Step 2: Add the control**

In `web/components/AppShell.tsx`, add `Modal` to the `antd` import list (alongside `Segmented`, already imported), and add `setAdapter` to the existing import from `@/lib/api`.

Add the handler inside the component, above the returned JSX:

```tsx
  const switchAdapter = (next: string) => {
    if (next === status?.adapter) return
    Modal.confirm({
      title: next === 'fake' ? 'Switch to fake data?' : 'Switch to Graph data?',
      content:
        'The app will reload and show the other dataset. Nothing is deleted — ' +
        'the dataset you are leaving is kept exactly as it is.',
      okText: 'Switch',
      onOk: async () => {
        await setAdapter(next as 'graph' | 'fake')
        // Everything on screen came from a database that is no longer live,
        // and the profile being viewed may not exist in the other dataset.
        window.location.assign('/')
      },
    })
  }
```

In the header strip, immediately before the `<div style={{ flex: 1 }} />` spacer, add the control:

```tsx
          <Text type="secondary" style={{ fontSize: 11, letterSpacing: '.06em', marginLeft: 16 }}>
            DATA
          </Text>
          <Segmented
            size="small"
            value={status?.adapter ?? 'graph'}
            onChange={(v) => switchAdapter(v as string)}
            options={[
              { value: 'graph', label: 'Graph' },
              { value: 'fake', label: 'Fake' },
            ]}
          />
```

- [ ] **Step 3: Run the typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: PASS, no output.

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts web/components/AppShell.tsx
git commit -m "feat(web): add a confirmed data-source toggle to the header"
```

---

### Task 8: End-to-end coverage

One spec, fully deterministic and network-free. The e2e stack runs on fake; switching *to* graph with no token configured makes `GraphAdapter` raise `IgChallenge` before any HTTP call.

**Files:**
- Create: `web/e2e/adapter-toggle.spec.ts`
- Test: the Playwright suite itself

**Interfaces:**
- Consumes: the control from Task 7 and the endpoint from Task 6.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `web/e2e/adapter-toggle.spec.ts`. Read an existing spec such as `web/e2e/preview.spec.ts` first and follow its setup helpers and selectors rather than inventing new ones:

```ts
import { expect, test } from '@playwright/test'

test('the header shows which dataset is live', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('radio', { name: 'Fake' })).toBeChecked()
})

test('switching asks for confirmation and can be cancelled', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Graph' }).click()

  await expect(page.getByText('Switch to Graph data?')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  await expect(page.getByRole('radio', { name: 'Fake' })).toBeChecked()
})

test('confirming the switch reloads onto the other dataset', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Graph' }).click()
  await page.getByRole('button', { name: 'Switch' }).click()

  await page.waitForURL('**/')
  await expect(page.getByRole('radio', { name: 'Graph' })).toBeChecked()

  // The e2e stack has no Graph token, so the seeded fake profiles are gone.
  await expect(page.getByText('nike')).toHaveCount(0)
})
```

- [ ] **Step 2: Run the suite**

Run: `bash scripts/e2e-native.sh`
Expected: the three new tests PASS. This task verifies Task 7 rather than
driving it — the control already exists by now, so a red-first run is not
available. To confirm the specs are real rather than vacuously passing,
comment out the `<Segmented>` block added in Task 7, re-run, and check that
all three fail; then restore it.

- [ ] **Step 3: Adjust selectors to the real DOM**

Ant Design's `Segmented` renders radio inputs with labels. If `getByRole('radio', { name: 'Graph' })` does not match, inspect the rendered markup and switch to the same selector style the existing specs use for the theme `Segmented`, which is the identical component. Do not add `data-testid` attributes unless the existing specs already rely on them.

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `bash scripts/e2e-native.sh`
Expected: 39 passed.

Then confirm the backend is still green:

Run: `cd api && python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/e2e/adapter-toggle.spec.ts
git commit -m "test(web): cover the data-source toggle end to end"
```

---

## Verification

After Task 8, confirm the spec's success criteria:

1. `cd api && python -m pytest tests/ -q` — green, no network.
2. `bash scripts/e2e-native.sh` — green.
3. Start the stack, switch to fake, confirm the seeded dataset appears; switch back to graph and confirm the real dataset is unchanged and was not re-synced.
4. `ls data/fake/` — a separate `app.db` and `media/` exist; nothing written under fake appears at the top level.
5. Restart the API and confirm it comes up on the last selected adapter.
6. Trip the breaker on one adapter, switch, and confirm the banner is clear.
