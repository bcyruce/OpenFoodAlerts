import httpx
import pytest

from openfoodalerts.http import USER_AGENT, PoliteClient


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def make_client(handler: httpx.MockTransport, t: FakeTime, interval: float = 0.0) -> PoliteClient:
    return PoliteClient(min_interval=interval, transport=handler, sleep=t.sleep, clock=t.clock)


def test_sends_project_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200)

    t = FakeTime()
    with make_client(httpx.MockTransport(handler), t) as client:
        client.get("https://example.test/")
    assert seen == [USER_AGENT]


def test_retries_5xx_then_succeeds() -> None:
    statuses = iter([503, 502, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses))

    t = FakeTime()
    with make_client(httpx.MockTransport(handler), t) as client:
        response = client.get("https://example.test/")
        assert response.status_code == 200
        assert client.request_count == 3


def test_gives_up_after_five_attempts_and_returns_last_5xx() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    t = FakeTime()
    with make_client(httpx.MockTransport(handler), t) as client:
        response = client.get("https://example.test/")
    assert response.status_code == 500
    assert calls == 5


def test_retries_network_errors_and_reraises_when_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    t = FakeTime()
    with make_client(httpx.MockTransport(handler), t) as client, pytest.raises(httpx.ConnectError):
        client.get("https://example.test/")
    assert len(t.sleeps) == 4


def test_4xx_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    t = FakeTime()
    with make_client(httpx.MockTransport(handler), t) as client:
        assert client.get("https://example.test/").status_code == 404
    assert calls == 1


def test_keeps_minimum_interval_between_requests() -> None:
    t = FakeTime()
    with make_client(httpx.MockTransport(lambda r: httpx.Response(200)), t, interval=3.0) as c:
        c.get("https://example.test/a")
        t.now += 1.0
        c.get("https://example.test/b")
        c.post("https://example.test/c")
    assert t.sleeps == [2.0, 3.0]


def test_pause_sleeps() -> None:
    t = FakeTime()
    with make_client(httpx.MockTransport(lambda r: httpx.Response(200)), t) as c:
        c.pause(60)
    assert t.sleeps == [60]
