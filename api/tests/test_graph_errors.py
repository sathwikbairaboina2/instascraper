import pytest

from app.ig import graph, types as t


def envelope(code, message="boom", subcode=None):
    error = {"message": message, "type": "OAuthException", "code": code}
    if subcode is not None:
        error["error_subcode"] = subcode
    return {"error": error}


@pytest.mark.parametrize("code", [190, 102, 200, 250, 299])
def test_auth_and_permission_codes_are_challenges(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgChallenge)


@pytest.mark.parametrize("code", [4, 17, 32, 613])
def test_throttling_codes_are_rate_limits(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgRateLimited)


@pytest.mark.parametrize("code", [1, 2])
def test_transient_meta_codes_are_transient(code):
    assert isinstance(graph.classify(400, envelope(code)), t.IgTransient)


def test_server_errors_are_transient():
    assert isinstance(graph.classify(503, {}), t.IgTransient)


def test_unknown_code_defaults_to_transient():
    assert isinstance(graph.classify(400, envelope(99999)), t.IgTransient)


def test_missing_user_is_not_found():
    exc = graph.classify(400, envelope(110, "Invalid user id"))
    assert isinstance(exc, t.IgNotFound)


def test_non_business_target_is_out_of_scope():
    exc = graph.classify(
        400, envelope(100, "The user is not an Instagram Business or Creator account")
    )
    assert isinstance(exc, t.IgPrivate)


def test_rate_limit_carries_the_wait_meta_asked_for():
    headers = {
        "x-business-use-case-usage": '{"1":[{"estimated_time_to_regain_access":7}]}'
    }
    exc = graph.classify(400, envelope(4), headers)
    assert isinstance(exc, t.IgRateLimited)
    assert exc.retry_after == 420.0


def test_rate_limit_without_an_estimate_has_no_retry_after():
    exc = graph.classify(400, envelope(4), {})
    assert exc.retry_after is None


def test_token_never_survives_into_an_error_message():
    exc = graph.classify(400, envelope(190, "Bad token SECRET123"), {}, token="SECRET123")
    assert "SECRET123" not in str(exc)
    assert "[redacted]" in str(exc)


def test_usage_percent_reads_the_highest_counter():
    headers = {"x-app-usage": '{"call_count":12,"total_cputime":91,"total_time":3}'}
    assert graph.usage_percent(headers) == 91.0


def test_usage_percent_is_zero_when_the_header_is_absent_or_junk():
    assert graph.usage_percent({}) == 0.0
    assert graph.usage_percent({"x-app-usage": "not json"}) == 0.0
