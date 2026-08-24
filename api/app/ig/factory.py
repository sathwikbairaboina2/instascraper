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

    return GraphAdapter(settings)
