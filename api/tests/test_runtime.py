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
