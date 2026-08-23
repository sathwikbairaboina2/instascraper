from app.ig import types as t
from app.ig.login import main


class OkAdapter:
    def __init__(self):
        self.called = False

    def login(self):
        self.called = True


class FailingAdapter:
    def login(self):
        raise t.IgChallenge("checkpoint_required")


def test_login_success_returns_zero(settings):
    adapter = OkAdapter()
    lines = []
    code = main(settings=settings, adapter_factory=lambda _s: adapter, out=lines.append)
    assert code == 0
    assert adapter.called is True
    assert any("session saved" in line.lower() for line in lines)


def test_login_failure_returns_one_and_explains(settings):
    lines = []
    code = main(settings=settings, adapter_factory=lambda _s: FailingAdapter(), out=lines.append)
    assert code == 1
    assert any("checkpoint_required" in line for line in lines)


def test_login_refuses_without_credentials(settings):
    blank = settings.__class__(**{**settings.__dict__, "ig_username": ""})
    lines = []
    code = main(settings=blank, adapter_factory=lambda _s: OkAdapter(), out=lines.append)
    assert code == 1
    assert any("IG_USERNAME" in line for line in lines)
