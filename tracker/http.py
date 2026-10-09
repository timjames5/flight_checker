"""HTTP helper with retries and exponential backoff."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

import requests

log = logging.getLogger(__name__)

# 424 is Ignav's "upstream provider failed" status, which is worth retrying.
RETRYABLE_STATUS = {408, 424, 429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") or {}
        if isinstance(err, dict) and err.get("message"):
            return f"{err.get('code', resp.status_code)}: {err['message']}"
        if isinstance(body.get("message"), str):
            return body["message"]
    except ValueError:
        pass
    return (resp.text or resp.reason or "")[:300]


def backoff_delay(attempt: int, base: float, retry_after: str | None = None) -> float:
    """Seconds to wait after failed attempt number `attempt` (1-based)."""
    if retry_after:
        try:
            return min(float(retry_after), 120.0)
        except ValueError:
            pass
    return base * (2 ** (attempt - 1)) + random.uniform(0, base / 2)


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    backoff_base: float = 2.0,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> requests.Response:
    """Send a request, retrying on network errors and retryable status codes.

    Raises ApiError when the request still fails after max_attempts, or
    immediately for non-retryable errors such as 400 or 401.
    """
    last_error: ApiError | None = None
    for attempt in range(1, max_attempts + 1):
        retry_after = None
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = ApiError(f"network error: {exc}")
        else:
            if resp.status_code < 400:
                return resp
            last_error = ApiError(
                f"HTTP {resp.status_code} from {url}: {_error_message(resp)}",
                status=resp.status_code,
            )
            if resp.status_code not in RETRYABLE_STATUS:
                raise last_error
            retry_after = resp.headers.get("Retry-After")

        if attempt < max_attempts:
            delay = backoff_delay(attempt, backoff_base, retry_after)
            log.warning("%s (attempt %d/%d), retrying in %.1fs", last_error, attempt, max_attempts, delay)
            sleep(delay)

    assert last_error is not None
    raise last_error
