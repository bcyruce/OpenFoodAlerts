"""Shared HTTP client that follows the courtesy rules common to all Sources (spec §3).

Requests are sequential, carry the project User-Agent, keep a minimum interval between
requests, and retry network errors and 5xx responses with exponential backoff (at most
5 attempts). 4xx responses are returned to the caller unchanged (openFDA uses 404 for
"no results").
"""

import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "OpenFoodAlerts-bot/1.0 (+https://openfoodalerts.nl/about)"
MAX_ATTEMPTS = 5


class RetryableStatus(Exception):
    """A 5xx response that should be retried."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code} from {response.request.url}")
        self.response = response


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableStatus | httpx.TransportError)


class PoliteClient:
    """Sequential HTTP client with a minimum interval between requests.

    `sleep` and `clock` are injectable so tests run instantly.
    """

    def __init__(
        self,
        *,
        min_interval: float = 0.0,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        backoff_max: float = 60.0,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._backoff_max = backoff_max
        self.request_count = 0

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def pause(self, seconds: float) -> None:
        """Wait before the next request (e.g. when a Source signals a rate limit)."""
        self._sleep(seconds)

    def _wait_for_slot(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)

    def _send_once(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._wait_for_slot()
        try:
            response = self._client.request(method, url, **kwargs)
        finally:
            self._last_request_at = self._clock()
            self.request_count += 1
        if response.status_code >= 500:
            raise RetryableStatus(response)
        return response

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        def sleep_between_attempts(seconds: float) -> None:
            self._sleep(seconds)

        def reraise_last(state: RetryCallState) -> httpx.Response:
            outcome = state.outcome
            assert outcome is not None
            exc = outcome.exception()
            if isinstance(exc, RetryableStatus):
                return exc.response
            assert exc is not None
            raise exc

        retrying = retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=1, min=1, max=self._backoff_max),
            sleep=sleep_between_attempts,
            retry_error_callback=reraise_last,
        )
        response: httpx.Response = retrying(self._send_once)(method, url, **kwargs)
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
