from app.ig import types as t


def test_canary_ok_against_the_fake(client):
    body = client.get("/api/health/canary?username=nike").json()
    assert body["ok"] is True
    assert body["checks"] == {"profile": True, "page": True, "media": True}
    assert body["error"] is None


def test_canary_reports_failure_without_raising(client):
    adapter = client.app_state.runtime.current.adapter
    adapter.raise_on("fetch_profile", t.IgChallenge("checkpoint_required"))

    body = client.get("/api/health/canary?username=nike").json()

    assert body["ok"] is False
    assert body["checks"]["profile"] is False
    assert "checkpoint_required" in body["error"]


def test_clear_breaker_resets_a_permanent_trip(client):
    client.app_state.breaker.trip_permanent("session invalid")

    assert client.post("/api/health/clear-breaker").json() == {"cleared": True}
    assert client.get("/api/status").json()["breaker"]["tripped"] is False
