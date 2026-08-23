from app.worker.breaker import Breaker


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_starts_clear():
    b = Breaker(clock=FakeClock())
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_temporary_trip_expires():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_temporary(900, "rate limited")
    assert b.wait_seconds() == 900
    clock.advance(899)
    assert b.wait_seconds() == 1
    clock.advance(1)
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_permanent_trip_never_expires():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_permanent("session invalid")
    clock.advance(10_000)
    assert b.wait_seconds() == float("inf")
    assert b.state() == {
        "tripped": True,
        "permanent": True,
        "reason": "session invalid",
        "seconds_remaining": None,
    }


def test_permanent_trip_survives_a_later_temporary_trip():
    """A challenge must not be downgraded into a 15-minute nap."""
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_permanent("session invalid")
    b.trip_temporary(5, "rate limited")
    clock.advance(1_000)
    assert b.wait_seconds() == float("inf")
    assert b.state()["reason"] == "session invalid"


def test_clear_resets_everything():
    b = Breaker(clock=FakeClock())
    b.trip_permanent("session invalid")
    b.clear()
    assert b.wait_seconds() == 0.0
    assert b.state()["tripped"] is False


def test_temporary_trip_extends_but_never_shortens():
    clock = FakeClock()
    b = Breaker(clock=clock)
    b.trip_temporary(900, "first")
    b.trip_temporary(10, "second")
    assert b.wait_seconds() == 900
    b.trip_temporary(1800, "third")
    assert b.wait_seconds() == 1800
    assert b.state()["reason"] == "third"
