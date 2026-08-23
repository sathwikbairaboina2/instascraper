"""Anonymous mode: no credentials, public profiles only.

Instagram currently 429s unauthenticated profile lookups on the first
request, so the point of these tests is not that anonymous browsing works
-- it is that the app runs without credentials and reports the refusal
instead of hanging or crashing.
"""
import pytest

from app.config import Settings, load_settings
from app.ig import types as t
from app.ig.rate import PacedRateController


def _settings(**over) -> Settings:
    base = dict(
        ig_username="", ig_password="",
        db_path=None, media_dir=None, session_dir=None, out_dir=None,
        page_size=36, ig_min_interval=3, ig_backoff=900, adapter="real",
        anonymous=True, max_sleep=60,
    )
    base.update(over)
    return Settings(**base)


def test_missing_credentials_implies_anonymous(monkeypatch):
    for key in ("IG_USERNAME", "IG_PASSWORD", "IG_ANONYMOUS"):
        monkeypatch.delenv(key, raising=False)
    assert load_settings().anonymous is True


def test_credentials_imply_authenticated(monkeypatch):
    monkeypatch.setenv("IG_USERNAME", "burner")
    monkeypatch.setenv("IG_PASSWORD", "hunter2")
    monkeypatch.delenv("IG_ANONYMOUS", raising=False)
    assert load_settings().anonymous is False


def test_anonymous_can_be_forced_even_with_credentials(monkeypatch):
    monkeypatch.setenv("IG_USERNAME", "burner")
    monkeypatch.setenv("IG_PASSWORD", "hunter2")
    monkeypatch.setenv("IG_ANONYMOUS", "1")
    assert load_settings().anonymous is True


def test_rate_controller_still_enforces_the_floor():
    slept = []
    rc = PacedRateController(context=None, min_interval=3, max_sleep=60, sleep=slept.append)
    rc.sleep(0.5)
    assert slept == [3]


def test_rate_controller_raises_rather_than_sleeping_for_half_an_hour():
    """Instaloader sleeps internally on a 429. Left alone that blocks the one
    worker thread for 30 minutes with no breaker trip and no UI feedback."""
    slept = []
    rc = PacedRateController(context=None, min_interval=3, max_sleep=60, sleep=slept.append)

    with pytest.raises(t.IgRateLimited):
        rc.sleep(1800)

    assert slept == [], "must not sleep at all when handing control back"


def test_a_long_sleep_classifies_as_rate_limited():
    import instaloader.exceptions as ie

    from app.ig.adapter import classify

    assert isinstance(classify(ie.TooManyRequestsException("429")), t.IgRateLimited)


def test_anonymous_adapter_never_logs_in(tmp_path):
    from app.ig.adapter import InstaloaderAdapter

    s = _settings(
        db_path=tmp_path / "a.db", media_dir=tmp_path / "m",
        session_dir=tmp_path / "s", out_dir=tmp_path / "o",
    )
    adapter = InstaloaderAdapter(s)
    calls = []
    adapter.login = lambda: calls.append(1)  # type: ignore[method-assign]

    adapter._ensure_login()

    assert calls == [], "anonymous mode must not attempt a login"


def test_login_refuses_in_anonymous_mode(tmp_path):
    from app.ig.adapter import InstaloaderAdapter

    s = _settings(
        db_path=tmp_path / "a.db", media_dir=tmp_path / "m",
        session_dir=tmp_path / "s", out_dir=tmp_path / "o",
    )
    with pytest.raises(t.IgChallenge) as exc:
        InstaloaderAdapter(s).login()
    assert "anonymous" in str(exc.value).lower()


def test_status_reports_anonymous(client):
    assert client.get("/api/status").json()["anonymous"] is True
