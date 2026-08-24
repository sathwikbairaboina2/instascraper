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
