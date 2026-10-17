"""`ofa send-instant [--dry-run]` from the command line."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from tests.mail_data import add_notification, add_subscription

runner = CliRunner()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("MAILER_DATABASE_URL", raising=False)  # falls back to DATABASE_URL
    monkeypatch.setenv("EMAIL_TRANSPORT", "outbox")
    monkeypatch.setenv("EMAIL_OUTBOX_DIR", str(tmp_path))
    monkeypatch.setenv("SITE_URL", "https://example.test")
    monkeypatch.delenv("OFA_TOKEN_SECRET", raising=False)
    return tmp_path


def seed(db: Connection) -> None:
    now = datetime.now(UTC)
    add_subscription(
        db, "cli@example.com", confirmed_at=now - timedelta(days=2), instant_sources=["rasff"]
    )
    add_notification(
        db,
        "rasff",
        "2026.0001",
        notification_type="alert notification",
        first_seen_at=now - timedelta(hours=1),
    )
    db.commit()


def test_dry_run_sends_nothing(db: Connection, env: Path) -> None:
    seed(db)
    result = runner.invoke(app, ["send-instant", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would send 1" in result.output
    assert "cli@example.com" not in result.output
    assert list(env.glob("*.json")) == []


def test_sends_once(db: Connection, env: Path) -> None:
    seed(db)
    first = runner.invoke(app, ["send-instant"])
    assert first.exit_code == 0, first.output
    assert "sent 1" in first.output
    [outbox] = list(env.glob("*.json"))
    message = json.loads(outbox.read_text(encoding="utf-8"))
    assert message["to"] == "cli@example.com"
    assert message["subject"].startswith("RASFF, alert notification: ")
    assert message["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    again = runner.invoke(app, ["send-instant"])
    assert "sent 0" in again.output
    assert len(list(env.glob("*.json"))) == 1


def test_missing_transport_is_a_usage_error(
    db: Connection, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EMAIL_TRANSPORT")
    result = runner.invoke(app, ["send-instant"])
    assert result.exit_code == 2
    assert "EMAIL_TRANSPORT" in result.output
