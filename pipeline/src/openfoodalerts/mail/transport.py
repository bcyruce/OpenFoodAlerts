"""Sending email (spec §10). The twin of web/lib/email/transport.ts; `EMAIL_TRANSPORT`
picks the implementation:

- `brevo`: Brevo transactional API (production). Needs BREVO_API_KEY and EMAIL_FROM
  (EMAIL_FROM_NAME defaults to "OpenFoodAlerts"). Not yet tried against the real service.
- `outbox`: writes each message as JSON into EMAIL_OUTBOX_DIR (tests, local runs).
- `log`: prints the message to stdout (local development only: it shows addresses and
  manage tokens).

Unlike the website there is no default: a job started without EMAIL_TRANSPORT refuses
to run rather than silently not sending.

Failures come in two kinds, which the jobs treat differently (see mail/deliveries.py):
`DeliveryFailed` means the provider certainly did not accept the message (connection
refused, an error response), so it may be retried; `DeliveryUncertain` means it may
have been sent (e.g. a timeout after the request went out), so it must not be retried.
"""

import json
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Extra headers, e.g. List-Unsubscribe for Digest and Instant emails.
    headers: dict[str, str] = field(default_factory=dict)
    # Kind of email for the provider's statistics: confirm, digest, instant.
    tag: str | None = None


@dataclass(frozen=True)
class SendResult:
    message_id: str | None


class DeliveryFailed(Exception):
    """The provider did not accept the message; sending it again is safe."""


class DeliveryUncertain(Exception):
    """The message may or may not have been accepted; do not send it again."""


class EmailTransport(Protocol):
    name: str

    def send(self, message: EmailMessage) -> SendResult: ...


class BrevoTransport:
    name = "brevo"

    def __init__(
        self,
        *,
        api_key: str,
        sender_email: str,
        sender_name: str = "OpenFoodAlerts",
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._sender = {"email": sender_email, "name": sender_name}
        self._client = client or httpx.Client(timeout=15.0)

    def send(self, message: EmailMessage) -> SendResult:
        body: dict[str, object] = {
            "sender": self._sender,
            "to": [{"email": message.to}],
            "subject": message.subject,
            "textContent": message.text,
            "htmlContent": message.html,
        }
        if message.headers:
            body["headers"] = message.headers
        if message.tag:
            body["tags"] = [message.tag]
        try:
            response = self._client.post(
                BREVO_URL,
                json=body,
                headers={"api-key": self._api_key, "accept": "application/json"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise DeliveryFailed(f"Brevo unreachable: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise DeliveryUncertain(f"Brevo request interrupted: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise DeliveryFailed(f"Brevo responded {response.status_code}: {response.text[:300]}")
        message_id = response.json().get("messageId")
        return SendResult(message_id=str(message_id) if message_id else None)


class OutboxTransport:
    name = "outbox"

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def send(self, message: EmailMessage) -> SendResult:
        self._dir.mkdir(parents=True, exist_ok=True)
        message_id = f"outbox-{uuid.uuid4()}"
        data = {**asdict(message), "messageId": message_id}
        path = self._dir / f"{message_id}.json"
        # Write then rename, so a reader polling the outbox never sees a half-written file.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return SendResult(message_id=message_id)


class LogTransport:
    name = "log"

    def send(self, message: EmailMessage) -> SendResult:
        sys.stdout.write(f"[email:log] to={message.to} subject={message.subject!r}\n")
        sys.stdout.write(message.text + "\n")
        return SendResult(message_id=None)


class MemoryTransport:
    """Test double: keeps every message in `sent`."""

    name = "memory"

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> SendResult:
        self.sent.append(message)
        return SendResult(message_id=f"memory-{len(self.sent)}")


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ValueError(
            f"{name} is not set (needed for EMAIL_TRANSPORT={env.get('EMAIL_TRANSPORT')})"
        )
    return value


def transport_from_env(env: Mapping[str, str] | None = None) -> EmailTransport:
    env = os.environ if env is None else env
    kind = env.get("EMAIL_TRANSPORT")
    if kind == "brevo":
        return BrevoTransport(
            api_key=_required(env, "BREVO_API_KEY"),
            sender_email=_required(env, "EMAIL_FROM"),
            sender_name=env.get("EMAIL_FROM_NAME") or "OpenFoodAlerts",
        )
    if kind == "outbox":
        return OutboxTransport(Path(_required(env, "EMAIL_OUTBOX_DIR")))
    if kind == "log":
        return LogTransport()
    raise ValueError(f"EMAIL_TRANSPORT must be brevo, outbox or log (got {kind or 'nothing'})")
