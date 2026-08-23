import time
from typing import Callable

import instaloader


class PacedRateController(instaloader.RateController):
    """Adds a hard floor to the gap between the HTTP requests Instaloader
    makes internally, on top of its own 429 handling.

    The worker's Pacer covers gaps between adapter calls; this covers the
    several requests a single adapter call can make while paginating.
    """

    def __init__(
        self,
        context,
        min_interval: float,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if context is not None:
            super().__init__(context)
        self._min_interval = min_interval
        self._sleep = sleep

    def sleep(self, secs: float) -> None:
        self._sleep(max(secs, self._min_interval))
