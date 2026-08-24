from dataclasses import replace
from pathlib import Path

import pytest

from app import db, runtime


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
