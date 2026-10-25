"""Email transports for the Digest and Instant email (the twin of web/lib/email/transport.ts)."""

import json
from pathlib import Path

import httpx
import pytest

from openfoodalerts.mail.transport import (
    BrevoTransport,
    DeliveryFailed,
    DeliveryUncertain,
    EmailMessage,
    LogTransport,
    MemoryTransport,
    OutboxTransport,
    transport_from_env,
)

MESSAGE = EmailMessage(
    to="reader@example.com",
    subject="Digest",
    text="hello",
    html="<p>hello</p>",
    headers={"List-Unsubscribe": "<https://x.test/u>"},
    tag="digest",
)


def brevo(handler: httpx.MockTransport) -> BrevoTransport:
    return BrevoTransport(
        api_key="key-1",
        sender_email="noreply@openfoodalerts.nl",
        sender_name="OpenFoodAlerts",
        client=httpx.Client(transport=handler),
    )


def test_brevo_posts_the_transactional_api_and_returns_the_message_id() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "<abc@smtp-relay.brevo.com>"})

    result = brevo(httpx.MockTransport(handle)).send(MESSAGE)

    assert result.message_id == "<abc@smtp-relay.brevo.com>"
    request = seen[0]
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == "key-1"
    assert json.loads(request.content) == {
        "sender": {"email": "noreply@openfoodalerts.nl", "name": "OpenFoodAlerts"},
        "to": [{"email": "reader@example.com", "contactPixelTrackingConsent": False}],
        "subject": "Digest",
        "textContent": "hello",
        "htmlContent": "<p>hello</p>",
        "headers": {"List-Unsubscribe": "<https://x.test/u>"},
        "tags": ["digest"],
    }


def test_brevo_error_responses_mean_not_sent() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "invalid_parameter"})

    with pytest.raises(DeliveryFailed, match="400"):
        brevo(httpx.MockTransport(handle)).send(MESSAGE)


def test_brevo_connection_refused_means_not_sent() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DeliveryFailed):
        brevo(httpx.MockTransport(handle)).send(MESSAGE)


def test_brevo_timeout_after_sending_is_uncertain() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DeliveryUncertain):
        brevo(httpx.MockTransport(handle)).send(MESSAGE)


def test_outbox_writes_one_json_file_per_message(tmp_path: Path) -> None:
    result = OutboxTransport(tmp_path).send(MESSAGE)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["to"] == "reader@example.com"
    assert data["headers"] == MESSAGE.headers
    assert data["messageId"] == result.message_id


def test_memory_keeps_messages() -> None:
    memory = MemoryTransport()
    assert memory.send(MESSAGE).message_id == "memory-1"
    assert memory.sent == [MESSAGE]


def test_log_prints_the_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert LogTransport().send(MESSAGE).message_id is None
    assert "reader@example.com" in capsys.readouterr().out


def test_transport_from_env(tmp_path: Path) -> None:
    assert isinstance(
        transport_from_env({"EMAIL_TRANSPORT": "outbox", "EMAIL_OUTBOX_DIR": str(tmp_path)}),
        OutboxTransport,
    )
    assert isinstance(transport_from_env({"EMAIL_TRANSPORT": "log"}), LogTransport)
    brevo_env = {"EMAIL_TRANSPORT": "brevo", "BREVO_API_KEY": "k", "EMAIL_FROM": "a@b.nl"}
    assert isinstance(transport_from_env(brevo_env), BrevoTransport)
    with pytest.raises(ValueError, match="BREVO_API_KEY"):
        transport_from_env({"EMAIL_TRANSPORT": "brevo", "EMAIL_FROM": "a@b.nl"})
    # Unlike the website there is no implicit default: the job must be told how to send.
    with pytest.raises(ValueError, match="EMAIL_TRANSPORT"):
        transport_from_env({})
