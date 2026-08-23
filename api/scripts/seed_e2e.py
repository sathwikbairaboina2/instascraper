"""Deterministic database seed for the Playwright suite.

Runs the real handlers against the fake adapter, so the seeded state is
produced by production code paths rather than hand-written SQL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.config import load_settings
from app.ig.fake import FakeAdapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def main() -> int:
    settings = load_settings()
    conn = db.get_conn(settings)
    db.init_schema(conn)
    for directory in (settings.media_dir, settings.out_dir):
        directory.mkdir(parents=True, exist_ok=True)

    adapter = FakeAdapter()
    adapter.add_profile("nike", post_count=8)
    adapter.add_posts("nike", count=6)
    adapter.add_posts("nike", count=2, child_count=3)

    ctx = HandlerContext(
        conn=conn, adapter=adapter, settings=settings,
        pacer=Pacer(0.0), enqueue=lambda *a: None,
    )
    handlers.handle_profile_sync(ctx, {"username": "nike"})
    while conn.execute(
        "SELECT next_cursor FROM profiles WHERE username='nike'"
    ).fetchone()["next_cursor"] != "":
        handlers.handle_page_fetch(ctx, {"username": "nike"})

    conn.execute("UPDATE profiles SET tracked=1 WHERE username='nike'")
    print(
        "seeded",
        conn.execute("SELECT COUNT(*) c FROM media_items").fetchone()["c"],
        "items",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
