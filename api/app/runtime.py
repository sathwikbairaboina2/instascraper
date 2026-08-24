"""Which adapter is live, and where its data lives.

The adapter can change while the process runs, and each adapter keeps its
own database and media cache. Isolation is therefore enforced by the
filesystem rather than by every query remembering to filter.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from app import db
from app.config import Settings
from app.worker import sweep as sweep_module

NAMES = ("graph", "fake")
_STATE_FILE = "adapter.state"


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
