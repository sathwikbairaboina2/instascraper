import threading
import time
from typing import Callable


class Pacer:
    """Floor on the gap between consecutive Instagram-bound calls.

    Because exactly one thread calls wait(), this is a real global rate
    rather than a per-task intention.
    """

    def __init__(
        self,
        min_interval: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                gap = self._clock() - self._last
                remaining = self._min_interval - gap
                if remaining > 0:
                    self._sleep(remaining)
            self._last = self._clock()
