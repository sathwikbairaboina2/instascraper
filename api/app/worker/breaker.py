import threading
from typing import Callable

from app import clock as _clock


class Breaker:
    """Global gate on Instagram-bound work.

    Temporary trips (429) expire on their own. Permanent trips (login
    challenge, dead session) need a human and never expire by themselves --
    automatically retrying past a challenge is how a throttled account
    becomes a flagged one.
    """

    def __init__(self, clock: Callable[[], float] = _clock.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._until: float = 0.0
        self._permanent = False
        self._reason: str | None = None

    def trip_temporary(self, seconds: float, reason: str) -> None:
        with self._lock:
            until = self._clock() + seconds
            if until <= self._until:
                return  # an existing, longer nap already covers this
            self._until = until
            if not self._permanent:
                self._reason = reason

    def trip_permanent(self, reason: str) -> None:
        with self._lock:
            self._permanent = True
            self._reason = reason

    def clear(self) -> None:
        with self._lock:
            self._until = 0.0
            self._permanent = False
            self._reason = None

    def wait_seconds(self) -> float:
        with self._lock:
            if self._permanent:
                return float("inf")
            return max(0.0, self._until - self._clock())

    def state(self) -> dict:
        with self._lock:
            if self._permanent:
                return {
                    "tripped": True,
                    "permanent": True,
                    "reason": self._reason,
                    "seconds_remaining": None,
                }
            remaining = max(0.0, self._until - self._clock())
            if remaining <= 0:
                return {
                    "tripped": False,
                    "permanent": False,
                    "reason": None,
                    "seconds_remaining": None,
                }
            return {
                "tripped": True,
                "permanent": False,
                "reason": self._reason,
                "seconds_remaining": remaining,
            }
