from app.worker.pacer import Pacer


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_first_call_does_not_wait():
    clock = FakeClock()
    slept = []
    p = Pacer(min_interval=3.0, sleep=slept.append, clock=clock)
    p.wait()
    assert slept == []


def test_second_immediate_call_waits_the_full_interval():
    clock = FakeClock()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock.t += seconds

    p = Pacer(min_interval=3.0, sleep=sleep, clock=clock)
    p.wait()
    p.wait()
    assert slept == [3.0]


def test_no_wait_when_enough_time_already_passed():
    clock = FakeClock()
    slept = []
    p = Pacer(min_interval=3.0, sleep=slept.append, clock=clock)
    p.wait()
    clock.t += 10
    p.wait()
    assert slept == []
