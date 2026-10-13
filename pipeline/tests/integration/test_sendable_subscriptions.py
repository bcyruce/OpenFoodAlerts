"""Who the mailer may email (spec §10, §11.1 #5): only active, not suppressed Subscriptions,
read through the `sendable_subscriptions` view, which is all ofa_mailer can see."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.subscriptions.sendable import is_sendable, sendable_subscriptions

PEPPER = "test-pepper"


def email_hash(email: str) -> str:
    """As the website stores it (web/lib/subscriptions/crypto.ts)."""
    return hmac.new(PEPPER.encode(), f"email:v1:{email}".encode(), hashlib.sha256).hexdigest()


def add(conn: Connection, email: str, status: str, *, hashed: bool = True) -> str:
    sid = str(uuid.uuid4())
    now = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO subscriptions (id, email, email_hash, locale, filters, status,
            manage_token_hash, consent_at, consent_text_version, confirmed_at, unsubscribed_at,
            confirm_token_hash, confirm_expires_at, instant_sources)
        VALUES (%s, %s, %s, 'nl', %s, %s, %s, %s, '2026-10-25', %s, %s, %s, %s, '{nvwa}')
        """,
        (
            sid,
            email,
            email_hash(email) if hashed else None,
            json.dumps({"sources": ["nvwa"]}),
            status,
            uuid.uuid4().hex,
            now,
            None if status == "pending" else now,
            now if status == "unsubscribed" else None,
            uuid.uuid4().hex if status == "pending" else None,
            now if status == "pending" else None,
        ),
    )
    return sid


@pytest.fixture
def mailer(db: Connection) -> Connection:
    add(db, "active@example.com", "active")
    add(db, "pending@example.com", "pending")
    add(db, "unsubscribed@example.com", "unsubscribed")
    add(db, "suppressed@example.com", "active")
    add(db, "unhashed@example.com", "active", hashed=False)
    db.execute(
        "INSERT INTO email_suppressions (email_hash) VALUES (%s)",
        (email_hash("suppressed@example.com"),),
    )
    db.commit()
    # Not SET LOCAL: stays in effect until the test rolls back.
    db.execute("SET ROLE ofa_mailer")
    return db


def test_only_active_unsuppressed_subscriptions_are_sendable(mailer: Connection) -> None:
    rows = sendable_subscriptions(mailer)
    assert [r["email"] for r in rows] == ["active@example.com"]
    assert rows[0]["locale"] == "nl"
    assert rows[0]["filters"] == {"sources": ["nvwa"]}
    assert rows[0]["instant_sources"] == ["nvwa"]
    assert rows[0]["include_unclassified"] is True


def test_rechecking_right_before_sending_sees_an_unsubscribe(db: Connection) -> None:
    sid = add(db, "active@example.com", "active")
    db.commit()
    assert is_sendable(db, sid)
    db.execute(
        "UPDATE subscriptions SET status = 'unsubscribed', unsubscribed_at = now() WHERE id = %s",
        (sid,),
    )
    db.commit()
    assert not is_sendable(db, sid)
    assert not is_sendable(db, str(uuid.uuid4()))


def test_the_mailer_cannot_read_the_tables_behind_the_view(mailer: Connection) -> None:
    for table in ("subscriptions", "email_suppressions"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            mailer.execute(f"SELECT 1 FROM {table}")
        mailer.rollback()
        mailer.execute("SET ROLE ofa_mailer")


def test_the_pipeline_role_cannot_read_the_view(db: Connection) -> None:
    db.execute("SET ROLE ofa_pipeline")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sendable_subscriptions(db)
    db.rollback()
