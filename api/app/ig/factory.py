"""Chooses the adapter.

Kept out of any adapter module so that deleting an implementation never
takes the factory with it.
"""

from app.config import Settings


def make_adapter(settings: Settings):
    if settings.adapter == "fake":
        # Test-only. The e2e stack runs a live server against the seeded
        # dataset, so this must return the same data the seed script wrote.
        from app.ig.fake import seeded_adapter

        return seeded_adapter()

    from app.ig.graph import GraphAdapter
    from app.ig.reels import ReelDownloader

    return GraphAdapter(
        settings, reel_downloader=ReelDownloader(settings, spend=_spend(settings))
    )


def _spend(settings: Settings):
    """Check both caps and record the attempt, in one indivisible step.

    Bound here rather than inside the downloader because adapters have no
    database access -- the hint mechanism exists for exactly that reason.
    Checking and recording together is what stops two callers each seeing
    the last slot as free.
    """

    def spend() -> None:
        from app import db
        from app.clock import now_iso
        from app.ig import types as t
        from app.services import quota

        conn = db.get_conn(settings)
        now = now_iso()
        for seconds, limit, label in (
            (3600, settings.reel_max_per_hour, "hourly"),
            (86400, settings.reel_max_per_day, "daily"),
        ):
            state = quota.window(conn, quota.REEL, seconds, limit, now)
            if state["used"] >= limit:
                raise t.IgQuotaSpent(
                    f"{label} reel cap spent ({state['used']}/{limit})",
                    resets_at=state["resets_at"],
                )
        quota.record(conn, quota.REEL, now)

    return spend
