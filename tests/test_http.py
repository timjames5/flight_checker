import pytest
import requests

from tracker.http import ApiError, request_with_retry


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(body)
        self.reason = ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, timeout=None, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run(outcomes, attempts=4):
    sleeps = []
    session = FakeSession(outcomes)
    try:
        resp = request_with_retry(session, "POST", "https://x/api", max_attempts=attempts,
                                  backoff_base=1, sleep=sleeps.append)
    except ApiError as exc:
        return exc, session.calls, sleeps
    return resp, session.calls, sleeps


def test_retries_then_succeeds():
    resp, calls, sleeps = run([FakeResponse(503), requests.ConnectionError("boom"), FakeResponse(200)])
    assert resp.status_code == 200
    assert calls == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]  # exponential backoff


def test_gives_up_after_max_attempts():
    err, calls, sleeps = run([FakeResponse(503)] * 3, attempts=3)
    assert isinstance(err, ApiError) and err.status == 503
    assert calls == 3 and len(sleeps) == 2


def test_no_retry_on_auth_error():
    body = {"error": {"type": "auth", "code": "invalid_api_key", "message": "Invalid API key"}}
    err, calls, sleeps = run([FakeResponse(401, body)])
    assert err.status == 401 and calls == 1 and sleeps == []
    assert "Invalid API key" in str(err)


def test_honours_retry_after():
    _, _, sleeps = run([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200)])
    assert sleeps == [7.0]


@pytest.mark.parametrize("status", [400, 402, 403, 404])
def test_client_errors_fail_fast(status):
    _, calls, _ = run([FakeResponse(status)])
    assert calls == 1
