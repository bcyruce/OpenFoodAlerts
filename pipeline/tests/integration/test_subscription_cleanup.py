"""`ofa cleanup-subscriptions` (spec §5, §11.1 #2, #6) and who may run it (spec §11.2)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.subscriptions.cleanup import cleanup_subscriptions

NOW = datetime.now(UTC)


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def add_subscription(
    conn: Connection,
    email: str,
    status: str,
    *,
    requested: datetime | None = None,
    unsubscribed: datetime | None = None,
) -> str:
    sid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO subscriptions (id, email, locale, filters, status, manage_token_hash,
            consent_at, consent_text_version, created_at, confirmed_at, unsubscribed_at,
            confirm_token_hash, confirm_expires_at)
        VALUES (%(id)s, %(email)s, 'en', %(filters)s, %(status)s, %(manage)s,
            %(requested)s, '2026-10-25', %(requested)s, %(confirmed)s, %(unsubscribed)s,
            %(confirm)s, %(expires)s)
        """,
        {
            "id": sid,
            "email": email,
            "filters": json.dumps({"sources": []}),
            "status": status,
            "manage": uuid.uuid4().hex,
            "requested": requested or days_ago(60),
            "confirmed": None if status == "pending" else days_ago(59),
            "unsubscribed": unsubscribed,
            "confirm": uuid.uuid4().hex if status == "pending" else None,
            "expires": (requested or NOW) + timedelta(days=1) if status == "pending" else None,
        },
    )
    return sid


def add_delivery(conn: Connection, subscription_id: str, sent: datetime) -> None:
    conn.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, sent_at) VALUES (%s, 'digest', %s)",
        (subscription_id, sent),
    )


def emails(conn: Connection) -> list[str]:
    return [r["email"] for r in conn.execute("SELECT email FROM subscriptions ORDER BY email")]


def delivery_ages(conn: Connection) -> list[int]:
    rows = conn.execute(
        "SELECT round(extract(epoch FROM now() - sent_at) / 86400)::int AS days "
        "FROM email_deliveries ORDER BY sent_at"
    )
    return [r["days"] for r in rows]


def test_deletes_only_what_is_past_its_retention_period(db: Connection) -> None:
    add_subscription(db, "pending-old@example.com", "pending", requested=days_ago(7.01))
    add_subscription(db, "pending-new@example.com", "pending", requested=days_ago(6.9))
    add_subscription(db, "unsub-old@example.com", "unsubscribed", unsubscribed=days_ago(29.01))
    add_subscription(db, "unsub-new@example.com", "unsubscribed", unsubscribed=days_ago(28.9))
    active = add_subscription(db, "active@example.com", "active", requested=days_ago(400))
    add_delivery(db, active, days_ago(366))
    add_delivery(db, active, days_ago(300))
    db.commit()

    counts = cleanup_subscriptions(db)

    assert counts == {"pending_deleted": 1, "unsubscribed_deleted": 1, "deliveries_deleted": 1}
    assert emails(db) == [
        "active@example.com",
        "pending-new@example.com",
        "unsub-new@example.com",
    ]
    assert delivery_ages(db) == [300]


def test_running_again_deletes_nothing_more(db: Connection) -> None:
    add_subscription(db, "pending-old@example.com", "pending", requested=days_ago(8))
    db.commit()
    cleanup_subscriptions(db)
    assert cleanup_subscriptions(db) == {
        "pending_deleted": 0,
        "unsubscribed_deleted": 0,
        "deliveries_deleted": 0,
    }


def test_deliveries_go_with_a_deleted_subscription(db: Connection) -> None:
    gone = add_subscription(db, "unsub-old@example.com", "unsubscribed", unsubscribed=days_ago(31))
    add_delivery(db, gone, days_ago(40))
    db.commit()
    cleanup_subscriptions(db)
    assert delivery_ages(db) == []


def as_role(conn: Connection, role: str) -> None:
    conn.execute(f"SET ROLE {role}")


def test_the_mailer_runs_it_but_cannot_delete_directly(db: Connection) -> None:
    add_subscription(db, "pending-old@example.com", "pending", requested=days_ago(8))
    db.commit()
    as_role(db, "ofa_mailer")
    assert cleanup_subscriptions(db)["pending_deleted"] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM subscriptions")
    db.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM email_deliveries")
    db.rollback()


def test_the_pipeline_role_cannot_run_it(db: Connection) -> None:
    as_role(db, "ofa_pipeline")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        cleanup_subscriptions(db)
    db.rollback()


def test_cli_logs_the_counts(db: Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    # Without MAILER_DATABASE_URL the job falls back to DATABASE_URL (the test database).
    monkeypatch.delenv("MAILER_DATABASE_URL", raising=False)
    add_subscription(db, "unsub-old@example.com", "unsubscribed", unsubscribed=days_ago(31))
    db.commit()
    result = CliRunner().invoke(app, ["cleanup-subscriptions"])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.startswith("{")]
    log: dict[str, Any] = json.loads(lines[-1])
    assert log["event"] == "job_finished"
    assert log["job"] == "cleanup-subscriptions"
    assert log["status"] == "ok"
    assert log["unsubscribed_deleted"] == 1
    assert emails(db) == []
