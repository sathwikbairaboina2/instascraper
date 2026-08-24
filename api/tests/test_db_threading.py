"""Regression tests for the request-scoped connection.

The API suite uses TestClient, which runs every handler on one thread and
therefore cannot catch a connection being used off the thread that made it.
Under uvicorn, FastAPI resolves a sync dependency and runs the sync endpoint
on different AnyIO threadpool threads, which is exactly that situation.
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import db


def test_new_conn_returns_a_distinct_connection_each_call(settings, conn):
    a = db.new_conn(settings)
    b = db.new_conn(settings)
    try:
        assert a is not b
        assert a is not conn
    finally:
        a.close()
        b.close()


def test_a_request_connection_survives_moving_between_threads(settings, conn):
    """Create on one thread, query on another -- what FastAPI actually does."""
    with ThreadPoolExecutor(max_workers=1) as maker:
        request_conn = maker.submit(db.new_conn, settings).result()

    try:
        with ThreadPoolExecutor(max_workers=1) as user:
            count = user.submit(
                lambda: request_conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"]
            ).result()
        assert count == 0
    finally:
        request_conn.close()


def test_thread_local_connection_is_still_per_thread(settings, conn):
    """The worker thread keeps its own long-lived connection."""
    with ThreadPoolExecutor(max_workers=1) as other:
        other_conn = other.submit(db.get_conn, settings).result()
    assert other_conn is not conn
    other_conn.close()


def test_writes_on_a_request_connection_are_visible_to_others(settings, conn):
    request_conn = db.new_conn(settings)
    try:
        request_conn.execute(
            "INSERT INTO profiles (username, tracked, created_at) VALUES ('x', 0, 't')"
        )
        assert conn.execute(
            "SELECT COUNT(*) c FROM profiles WHERE username='x'"
        ).fetchone()["c"] == 1
    finally:
        request_conn.close()


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
