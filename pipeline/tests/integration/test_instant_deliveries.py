"""Instant email claims in email_deliveries (migration 20261025001400), run as ofa_mailer:
one live claim per (Subscription, Notification), at most 5 per Amsterdam day."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.deliveries import claim_instant, mark_failed, mark_sent
from tests.mail_data import add_subscription

# 13:00 in Amsterdam (UTC+1 after the clocks went back that night).
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
CAP = 5


@pytest.fixture
def sid(db: Connection) -> str:
    sid = add_subscription(db, "a@example.com", confirmed_at=datetime(2026, 10, 1, tzinfo=UTC))
    db.commit()
    db.execute("SET ROLE ofa_mailer")
    return sid


def claim(
    db: Connection, sid: str, nid: int, now: datetime = NOW, first_seen_at: datetime | None = None
) -> object:
    return claim_instant(db, sid, nid, now=now, first_seen_at=first_seen_at or now, daily_cap=CAP)


def test_one_live_claim_per_subscription_and_notification(db: Connection, sid: str) -> None:
    first = claim(db, sid, 10)
    assert isinstance(first, int)
    assert claim(db, sid, 10) == "already"
    assert claim(db, sid, 10, NOW + timedelta(days=3)) == "already"
    mark_sent(db, first, "msg-1")
    assert claim(db, sid, 10) == "already"
    # Another Notification is another Instant email.
    assert isinstance(claim(db, sid, 11), int)


def test_a_failed_send_frees_the_pair_for_a_retry(db: Connection, sid: str) -> None:
    first = claim(db, sid, 10)
    assert isinstance(first, int)
    mark_failed(db, first)
    second = claim(db, sid, 10)
    assert isinstance(second, int) and second != first


def test_at_most_five_a_day_counting_in_amsterdam_time(db: Connection, sid: str) -> None:
    for nid in range(1, 6):
        assert isinstance(claim(db, sid, nid), int)
    assert claim(db, sid, 6) == "capped"
    # An already sent one is reported as such, not as capped.
    assert claim(db, sid, 1) == "already"
    # A failed attempt never reached anyone: it does not count.
    db.execute("UPDATE email_deliveries SET status = 'failed' WHERE instant_notification_id = 5")
    assert isinstance(claim(db, sid, 6), int)
    # 23:30 UTC is already the next day in Amsterdam: a fresh allowance.
    next_day = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)
    assert isinstance(claim(db, sid, 7, next_day), int)


def test_a_notification_capped_yesterday_is_not_sent_today(db: Connection, sid: str) -> None:
    yesterday = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)  # 22:00 in Amsterdam
    for nid in range(1, 6):
        assert isinstance(claim(db, sid, nid, yesterday), int)
    # First seen yesterday, over yesterday's cap: it went to the Digest only.
    assert claim(db, sid, 6, NOW, first_seen_at=yesterday) == "capped"
    # First seen today: today's allowance.
    assert isinstance(claim(db, sid, 7, NOW, first_seen_at=NOW), int)


def test_the_cap_is_per_subscription(db: Connection, sid: str) -> None:
    db.execute("RESET ROLE")
    other = add_subscription(db, "b@example.com", confirmed_at=datetime(2026, 10, 1, tzinfo=UTC))
    db.execute("SET ROLE ofa_mailer")
    for nid in range(1, 6):
        assert isinstance(claim(db, sid, nid), int)
    assert isinstance(claim(db, other, 1), int)


def test_an_instant_email_is_about_exactly_one_notification(db: Connection, sid: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO email_deliveries (subscription_id, kind, notification_ids)"
            " VALUES (%s, 'instant', '{1,2}')",
            (sid,),
        )
