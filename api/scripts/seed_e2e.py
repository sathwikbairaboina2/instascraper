"""Deterministic database seed for the Playwright suite.

Runs the real handlers against the fake adapter, so the seeded state is
produced by production code paths rather than hand-written SQL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, runtime
from app.config import load_settings
from app.ig.fake import seeded_adapter
from app.worker import handlers
from app.worker.pacer import Pacer
from app.worker.runner import HandlerContext


def main() -> int:
    base = load_settings()
    # The server derives the fake data root rather than using the configured
    # paths directly. Seeding the base path would leave it reading an empty
    # database next to a fully seeded one.
    settings = runtime.settings_for(base, base.adapter)
    conn = db.get_conn(settings)
    db.init_schema(conn)
    for directory in (settings.media_dir, settings.out_dir):
        directory.mkdir(parents=True, exist_ok=True)

    adapter = seeded_adapter()

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
