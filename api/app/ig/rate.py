import time
from typing import Callable

import instaloader

from app.ig import types as t


class PacedRateController(instaloader.RateController):
    """Adds a hard floor to the gap between the HTTP requests Instaloader
    makes internally, and refuses to nap for a long time on its behalf.

    The worker's Pacer covers gaps between adapter calls; this covers the
    several requests a single adapter call can make while paginating.

    The ceiling matters more than the floor. Instaloader handles a 429 by
    calling sleep() with however long it thinks it should wait -- half an
    hour is normal -- and then retrying. Honouring that would block the one
    worker thread for that whole period with no breaker trip and nothing
    shown in the UI. Raising instead hands control back to the worker, which
    trips the breaker, requeues the job, and tells the user when it resumes.
    Overriding sleep() this way is the extension point Instaloader documents.
    """

    def __init__(
        self,
        context,
        min_interval: float,
        max_sleep: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if context is not None:
            super().__init__(context)
        self._min_interval = min_interval
        self._max_sleep = max_sleep
        self._sleep = sleep

    def sleep(self, secs: float) -> None:
        if secs > self._max_sleep:
            # Carry the requested wait upwards so the breaker can honour it.
            raise t.IgRateLimited(
                f"Instagram asked us to wait {round(secs)}s",
                retry_after=secs,
            )
        self._sleep(max(secs, self._min_interval))
