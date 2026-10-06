"""RASFF client: request shapes and the rate-limit rules of spec §3.1 (no network)."""

import json
from collections.abc import Callable

import httpx
import pytest

from openfoodalerts.sources.rasff.client import RasffClient, RasffRateLimited


class FakeClock:
    """Monotonic clock that only moves when the client sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler, clock: FakeClock) -> RasffClient:
    return RasffClient.create(
        transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock
    )


def ok(remaining: int = 49, body: object | None = None) -> httpx.Response:
    return httpx.Response(
        200, json=body or {"ok": True}, headers={"X-Rate-Limit-Remaining": str(remaining)}
    )


def test_search_posts_the_page_and_filters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok()

    clock = FakeClock()
    client(handler, clock).search(3, filters={"ecValidDateFrom": "01-10-2026 00:00:00"})
    [request] = seen
    assert request.method == "POST"
    assert str(request.url).endswith(
        "/rasff-window/backend/public/notification/search/consolidated/en/"
    )
    assert json.loads(request.content) == {
        "parameters": {"pageNumber": 3, "itemsPerPage": 50},
        "ecValidDateFrom": "01-10-2026 00:00:00",
    }


def test_detail_gets_by_notif_id() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return ok()

    client(handler, FakeClock()).detail(881995)
    assert seen == [
        "https://webgate.ec.europa.eu/rasff-window/backend/public/notification/view/id/881995/en/"
    ]


def test_requests_are_three_seconds_apart() -> None:
    clock = FakeClock()
    c = client(lambda r: ok(), clock)
    c.detail(1)
    c.detail(2)
    c.detail(3)
    assert clock.sleeps == [3.0, 3.0]


def test_low_remaining_quota_pauses_a_minute() -> None:
    clock = FakeClock()
    remaining = iter([12, 9, 49])
    c = client(lambda r: ok(next(remaining)), clock)
    c.detail(1)
    c.detail(2)
    assert clock.sleeps == [3.0, 60.0]
    c.detail(3)  # the pause already covered the 3 s interval
    assert clock.sleeps == [3.0, 60.0]


def test_429_pauses_fifteen_minutes_logs_and_retries(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock()
    responses = iter([httpx.Response(429), ok(body={"id": 1})])
    response = client(lambda r: next(responses), clock).detail(1)
    assert response.json() == {"id": 1}
    assert clock.sleeps == [900.0]
    assert '"event": "rasff_rate_limited"' in capsys.readouterr().err


def test_429_that_persists_gives_up() -> None:
    clock = FakeClock()
    with pytest.raises(RasffRateLimited):
        client(lambda r: httpx.Response(429), clock).detail(1)
    assert clock.sleeps == [900.0, 900.0, 900.0]
