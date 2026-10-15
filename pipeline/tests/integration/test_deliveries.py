"""Claim-then-send bookkeeping in email_deliveries (migration 20261025001300), run as
ofa_mailer: one live Digest claim per Subscription and Amsterdam day."""

from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.deliveries import (
    claim_digest,
    daily_volume,
    last_sent_digest_at,
    mark_failed,
    mark_sent,
    sent_instantly,
)
from tests.mail_data import add_subscription

DAY = date(2026, 10, 25)
AS_OF = datetime(2026, 10, 25, 5, 0, tzinfo=UTC)


@pytest.fixture
def sid(db: Connection) -> str:
    sid = add_subscription(db, "a@example.com", confirmed_at=datetime(2026, 10, 1, tzinfo=UTC))
    db.commit()
    db.execute("SET ROLE ofa_mailer")
    return sid


def test_only_one_live_claim_per_subscription_and_day(db: Connection, sid: str) -> None:
    first = claim_digest(db, sid, AS_OF, [3, 1])
    assert first is not None
    assert claim_digest(db, sid, AS_OF, [3]) is None
    # A failed attempt frees the day for a retry.
    mark_failed(db, first)
    second = claim_digest(db, sid, AS_OF, [3])
    assert second is not None and second != first
    # Another day is another Digest.
    assert claim_digest(db, sid, AS_OF + timedelta(days=1), [3]) is not None


def test_the_window_starts_at_the_last_sent_digest(db: Connection, sid: str) -> None:
    assert last_sent_digest_at(db, sid) is None
    sending = claim_digest(db, sid, AS_OF, [1])
    assert sending is not None
    # Uncertain (still 'sending'): does not move the window.
    assert last_sent_digest_at(db, sid) is None
    earlier = claim_digest(db, sid, datetime(2026, 10, 24, 5, tzinfo=UTC), [1])
    assert earlier is not None
    mark_sent(db, earlier, "msg-1")
    assert last_sent_digest_at(db, sid) == datetime(2026, 10, 24, 5, tzinfo=UTC)


def test_sent_instantly_reads_instant_deliveries(db: Connection, sid: str) -> None:
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, notification_ids)"
        " VALUES (%s, 'instant', '{5,6}')",
        (sid,),
    )
    assert sent_instantly(db, sid, [5, 7]) == {5}
    assert sent_instantly(db, sid, []) == set()


def test_daily_volume_counts_every_kind_in_the_amsterdam_day(db: Connection, sid: str) -> None:
    for kind, sent_at in (
        ("confirm", datetime(2026, 10, 24, 22, 30, tzinfo=UTC)),  # 00:30 in Amsterdam
        ("instant", datetime(2026, 10, 25, 12, 0, tzinfo=UTC)),
        ("instant", datetime(2026, 10, 24, 21, 30, tzinfo=UTC)),  # the day before
    ):
        db.execute(
            "INSERT INTO email_deliveries (subscription_id, kind, sent_at) VALUES (%s, %s, %s)",
            (sid, kind, sent_at),
        )
    failed = claim_digest(db, sid, AS_OF, [1])
    assert failed is not None
    mark_failed(db, failed)  # never reached the provider: not counted
    assert claim_digest(db, sid, AS_OF, [1]) is not None
    assert daily_volume(db, DAY) == {"confirm": 1, "digest": 1, "instant": 1}


def test_the_mailer_may_only_change_status_and_provider_id(db: Connection, sid: str) -> None:
    claim = claim_digest(db, sid, AS_OF, [1])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE email_deliveries SET notification_ids = '{}' WHERE id = %s", (claim,))
    db.rollback()
    db.execute("SET ROLE ofa_mailer")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM email_deliveries")
    db.rollback()
