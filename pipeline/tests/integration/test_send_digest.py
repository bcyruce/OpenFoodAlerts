"""`ofa send-digest` (spec §5, §10.3, §10.5), run as ofa_mailer against the test database
with an in-memory transport and a fixed clock."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest

from openfoodalerts.db.connection import Connection, connect
from openfoodalerts.mail.digest import DigestRun, DigestSettings, send_digest
from openfoodalerts.mail.transport import (
    DeliveryFailed,
    DeliveryUncertain,
    EmailMessage,
    EmailTransport,
    MemoryTransport,
    SendResult,
)
from tests.conftest import get_test_database_url
from tests.mail_data import (
    add_country,
    add_hazard,
    add_notification,
    add_product_category,
    add_subscription,
    add_version,
    suppress,
)

# 2026-10-25 is the day summer time ends: 07:00 in Amsterdam is 06:00 UTC.
NOW = datetime(2026, 10, 25, 6, 0, tzinfo=UTC)
DAY = date(2026, 10, 25)
PREVIOUS = datetime(2026, 10, 24, 5, 0, tzinfo=UTC)  # 07:00 CEST the day before
CONFIRMED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
SALMONELLA = 21801  # RASFF hazard category: pathogenic micro-organisms
ALLERGENS = 21798
NUTS = 18427  # RASFF product category: nuts, nut products and seeds
SUBSCRIPTION_ID = "6f1c1f0e-3a8e-4c5a-9a53-2d1c3f6a7b8c"
# Shared test vector with web/lib/subscriptions/links.test.ts (ticket 29); not a credential.
TOKEN = "wJMitkeX3x6Sd7td2o5oR6N2GOoZW6yZk2swTVSV3C8"  # gitleaks:allow
SITE = "https://openfoodalerts.nl"
SETTINGS = DigestSettings(site_url=SITE, token_secret="secret-1")


def hours(n: float) -> timedelta:
    return timedelta(hours=n)


@pytest.fixture
def owner() -> Iterator[Connection]:
    """A second connection as the owner, for changes made "elsewhere" during a run."""
    conn = connect(get_test_database_url())
    try:
        yield conn
    finally:
        conn.close()


def as_mailer(db: Connection) -> Connection:
    db.commit()
    db.execute("SET ROLE ofa_mailer")
    db.commit()
    return db


def run(
    db: Connection, transport: EmailTransport, now: datetime = NOW, *, dry_run: bool = False
) -> DigestRun:
    return send_digest(db, transport, SETTINGS, now=now, dry_run=dry_run)


def record_previous_digest(db: Connection, sid: str, at: datetime = PREVIOUS) -> None:
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, sent_at, status,"
        " provider_message_id) VALUES (%s, 'digest', %s, 'sent', 'old')",
        (sid, at),
    )


def deliveries(db: Connection) -> list[dict[str, object]]:
    return db.execute(
        "SELECT subscription_id::text AS sid, kind, status, notification_ids, digest_date,"
        " provider_message_id, sent_at FROM email_deliveries WHERE kind = 'digest'"
        " ORDER BY id"
    ).fetchall()


def test_new_updated_and_rasff_news_sections(db: Connection) -> None:
    sid = add_subscription(
        db,
        "reader@example.com",
        confirmed_at=CONFIRMED,
        filters={"hazard_categories": [SALMONELLA]},
        include_unclassified=False,
        subscription_id=SUBSCRIPTION_ID,
    )
    record_previous_digest(db, sid)
    new = add_notification(
        db,
        "rasff",
        "2026.0001",
        title="Salmonella in sesame paste from Türkiye",
        first_seen_at=PREVIOUS + hours(6),
        risk_official="serious",
    )
    add_hazard(db, new, SALMONELLA)
    add_product_category(db, new, NUTS)
    add_country(db, new, "TR")
    instant = add_notification(
        db,
        "nvwa",
        "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-kip",
        title="Veiligheidswaarschuwing kip",
        first_seen_at=PREVIOUS + hours(7),
        summary_source="De NVWA waarschuwt voor salmonella in kip.\n\nMeer tekst.",
    )
    add_hazard(db, instant, SALMONELLA, provenance="ai")  # AI counts like official
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, notification_ids, sent_at)"
        " VALUES (%s, 'instant', %s, %s)",
        (sid, [instant], PREVIOUS + hours(7.5)),
    )
    updated = add_notification(
        db,
        "openfda",
        "H-0001-2027",
        first_seen_at=datetime(2026, 10, 1, tzinfo=UTC),
        hazard_text="Possible Salmonella contamination",
        risk_official="Class I",
    )
    add_hazard(db, updated, SALMONELLA)
    add_version(db, updated, 2, PREVIOUS + hours(8), substantial=True)
    minor = add_notification(
        db, "openfda", "H-0002-2027", first_seen_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    add_hazard(db, minor, SALMONELLA)
    add_version(db, minor, 2, PREVIOUS + hours(8), substantial=False)
    news = add_notification(
        db,
        "rasff",
        "2026.0002",
        notification_type="news",
        title="News about cheese",
        first_seen_at=PREVIOUS + hours(9),
    )
    add_hazard(db, news, ALLERGENS)  # does not match the filter; News is listed anyway
    old = add_notification(db, "rasff", "2026.0003", first_seen_at=PREVIOUS - hours(3))
    add_hazard(db, old, SALMONELLA)
    other = add_notification(db, "rasff", "2026.0004", first_seen_at=PREVIOUS + hours(2))
    add_hazard(db, other, ALLERGENS)
    nonfood = add_notification(
        db, "rasff", "2026.0005", first_seen_at=PREVIOUS + hours(2), product_type="non-food"
    )
    add_hazard(db, nonfood, SALMONELLA)
    as_mailer(db)
    transport = MemoryTransport()

    result = run(db, transport)

    assert [m.to for m in transport.sent] == ["reader@example.com"]
    message = transport.sent[0]
    text = message.text
    assert message.subject == "OpenFoodAlerts Digest, 2026-10-25"
    assert message.tag == "digest"
    assert "since 2026-10-24 07:00" in text
    new_part = text[text.index("New (2)") : text.index("Updated (1)")]
    assert "Salmonella in sesame paste from Türkiye" in new_part
    assert "Veiligheidswaarschuwing kip [sent instantly]" in new_part
    assert "RASFF · 2026-10-24 · Official severity: serious" in new_part
    assert "Hazard category: pathogenic micro-organisms (AI)" in new_part
    assert "Source text: De NVWA waarschuwt voor salmonella in kip." in new_part
    assert "Meer tekst" not in new_part  # one line
    assert f"{SITE}/en/n/rasff/2026.0001" in new_part
    assert f"{SITE}/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-kip" in new_part
    assert "https://example.test/rasff/2026.0001" in new_part  # official link
    updated_part = text[text.index("Updated (1)") : text.index("RASFF News (1)")]
    assert "openfda H-0001-2027" in updated_part
    assert "Substantial update seen on 2026-10-24" in updated_part
    assert "Source text: Possible Salmonella contamination" in updated_part
    assert "News about cheese" in text[text.index("RASFF News (1)") :]
    for absent in ("2026.0003", "2026.0004", "2026.0005", "H-0002-2027"):
        assert absent not in text
    [row] = [d for d in deliveries(db) if d["provider_message_id"] != "old"]
    assert row["status"] == "sent"
    assert row["provider_message_id"] == "memory-1"
    assert row["digest_date"] == DAY
    assert row["sent_at"] == NOW
    assert row["notification_ids"] == sorted([new, instant, updated, news])
    assert result.sent == 1


def test_headers_and_links_follow_the_ticket_29_contract(db: Connection) -> None:
    add_subscription(
        db, "a@example.com", confirmed_at=CONFIRMED, locale="nl", subscription_id=SUBSCRIPTION_ID
    )
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(1))
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    message = transport.sent[0]
    assert message.headers == {
        "List-Unsubscribe": f"<{SITE}/api/unsubscribe?token={TOKEN}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert f"{SITE}/nl/alerts/manage/{TOKEN}" in message.text
    assert f"{SITE}/api/unsubscribe?token={TOKEN}" in message.text
    assert f"{SITE}/nl/n/rasff/2026.0001" in message.text
    assert "Nieuw (1)" in message.text


def test_no_content_means_no_email(db: Connection) -> None:
    add_subscription(db, "a@example.com", confirmed_at=CONFIRMED, filters={"sources": ["openfda"]})
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(1))
    as_mailer(db)
    transport = MemoryTransport()
    result = run(db, transport)
    assert transport.sent == []
    assert deliveries(db) == []
    assert result.empty == 1


def test_the_first_digest_covers_everything_since_confirmation(db: Connection) -> None:
    add_subscription(db, "a@example.com", confirmed_at=NOW - hours(30))
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(29))
    add_notification(db, "rasff", "2026.0002", first_seen_at=NOW - hours(40))
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert "2026.0001" in transport.sent[0].text
    assert "2026.0002" not in transport.sent[0].text


def test_rows_committed_late_just_before_the_previous_digest_are_not_lost(db: Connection) -> None:
    sid = add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    listed = add_notification(db, "rasff", "2026.0001", first_seen_at=PREVIOUS - hours(0.5))
    updated = add_notification(db, "rasff", "2026.0002", first_seen_at=CONFIRMED)
    add_version(db, updated, 2, PREVIOUS - hours(0.5), substantial=True)
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, notification_ids, sent_at, status)"
        " VALUES (%s, 'digest', %s, %s, 'sent')",
        (sid, [listed, updated], PREVIOUS),
    )
    # first_seen_at is the parse transaction's start; it committed after the previous
    # Digest had looked, so that Digest could not see it.
    add_notification(db, "rasff", "2026.0003", first_seen_at=PREVIOUS - hours(0.5))
    late = add_notification(db, "rasff", "2026.0004", first_seen_at=CONFIRMED)
    add_version(db, late, 2, PREVIOUS - hours(0.5), substantial=True)
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    text = transport.sent[0].text
    assert "2026.0003" in text and "2026.0004" in text
    assert "2026.0001" not in text and "2026.0002" not in text


def test_backfilled_old_notifications_are_not_new(db: Connection) -> None:
    add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    add_notification(
        db,
        "rasff",
        "2012.0101",
        first_seen_at=NOW - hours(2),
        published_at=datetime(2012, 1, 3, tzinfo=UTC),
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert transport.sent == []


def test_at_most_one_digest_per_day_and_the_next_day_continues(
    db: Connection, owner: Connection
) -> None:
    add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    # Later the same Amsterdam day, with new content: nothing more.
    add_notification(owner, "rasff", "2026.0002", first_seen_at=NOW + hours(1))
    owner.commit()
    run(db, transport, now=NOW + hours(10))
    assert len(transport.sent) == 1
    # The next morning: only what is new since the first Digest.
    run(db, transport, now=NOW + hours(24))
    assert len(transport.sent) == 2
    assert "2026.0002" in transport.sent[1].text
    assert "2026.0001" not in transport.sent[1].text


class CrashAfterSending(MemoryTransport):
    """Hands the message over, then the process "dies" before recording it."""

    def send(self, message: EmailMessage) -> SendResult:
        super().send(message)
        raise SystemExit("killed")


def test_a_crash_after_sending_never_sends_twice(db: Connection) -> None:
    add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    as_mailer(db)
    crashing = CrashAfterSending()
    with pytest.raises(SystemExit):
        run(db, crashing)
    assert len(crashing.sent) == 1
    db.rollback()

    transport = MemoryTransport()
    run(db, transport, now=NOW + hours(1))
    assert transport.sent == []
    assert [d["status"] for d in deliveries(db)] == ["sending"]
    # It is uncertain whether that Digest arrived: the next one repeats its content.
    run(db, transport, now=NOW + hours(24))
    assert len(transport.sent) == 1
    assert "2026.0001" in transport.sent[0].text


def test_an_uncertain_send_is_not_retried_but_a_failed_one_is(db: Connection) -> None:
    add_subscription(db, "uncertain@example.com", confirmed_at=CONFIRMED)
    add_subscription(db, "failed@example.com", confirmed_at=CONFIRMED)
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    as_mailer(db)

    class Flaky(MemoryTransport):
        def send(self, message: EmailMessage) -> SendResult:
            if message.to == "uncertain@example.com":
                raise DeliveryUncertain("timeout")
            raise DeliveryFailed("503")

    result = run(db, Flaky())
    assert result.uncertain == 1
    assert result.failed == 1
    transport = MemoryTransport()
    run(db, transport, now=NOW + hours(1))
    assert [m.to for m in transport.sent] == ["failed@example.com"]
    statuses = sorted(str(d["status"]) for d in deliveries(db))
    assert statuses == ["failed", "sending", "sent"]


def test_only_sendable_subscriptions_get_mail(db: Connection, owner: Connection) -> None:
    add_subscription(db, "active@example.com", confirmed_at=CONFIRMED)
    add_subscription(db, "later@example.com", confirmed_at=CONFIRMED + hours(1))
    add_subscription(db, "unsubscribed@example.com", confirmed_at=CONFIRMED, status="unsubscribed")
    add_subscription(db, "suppressed@example.com", confirmed_at=CONFIRMED)
    suppress(db, "suppressed@example.com")
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    as_mailer(db)

    class UnsubscribesTheNextOne(MemoryTransport):
        def send(self, message: EmailMessage) -> SendResult:
            # Someone unsubscribes while the job runs: the next email must not go out.
            owner.execute(
                "UPDATE subscriptions SET status = 'unsubscribed', unsubscribed_at = now()"
                " WHERE email = 'later@example.com'"
            )
            owner.commit()
            return super().send(message)

    transport = UnsubscribesTheNextOne()
    result = run(db, transport)
    assert [m.to for m in transport.sent] == ["active@example.com"]
    assert result.unsendable == 1


def test_chinese_subscriptions_get_nvwa_only(db: Connection) -> None:
    add_subscription(
        db,
        "zh@example.com",
        confirmed_at=CONFIRMED,
        locale="zh",
        filters={"sources": ["nvwa"]},
        subscription_id=SUBSCRIPTION_ID,
    )
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    add_notification(
        db, "rasff", "2026.0002", first_seen_at=NOW - hours(2), notification_type="news"
    )
    add_notification(
        db,
        "nvwa",
        "/actueel/nieuws/2026/10/24/x",
        first_seen_at=NOW - hours(2),
        title="Veiligheidswaarschuwing x",
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    text = transport.sent[0].text
    assert "新增（1）" in text
    assert "Veiligheidswaarschuwing x" in text
    assert "官方严重度：未分级" in text
    assert "2026.000" not in text
    assert "RASFF News" not in text
    # Detail pages have no Chinese version; the manage page has.
    assert f"{SITE}/en/n/nvwa/actueel/nieuws/2026/10/24/x" in text
    assert f"{SITE}/zh/alerts/manage/{TOKEN}" in text


@pytest.mark.parametrize(("include_unclassified", "expected"), [(True, True), (False, False)])
def test_include_unclassified(db: Connection, include_unclassified: bool, expected: bool) -> None:
    add_subscription(
        db,
        "a@example.com",
        confirmed_at=CONFIRMED,
        filters={"hazard_categories": [SALMONELLA]},
        include_unclassified=include_unclassified,
    )
    add_notification(db, "nvwa", "/a/unclassified", first_seen_at=NOW - hours(2))
    other = add_notification(db, "nvwa", "/a/allergens", first_seen_at=NOW - hours(2))
    add_hazard(db, other, ALLERGENS, provenance="ai")
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert bool(transport.sent) is expected
    if expected:
        assert "/a/unclassified" in transport.sent[0].text
        assert "/a/allergens" not in transport.sent[0].text


def test_dry_run_sends_and_records_nothing(db: Connection) -> None:
    add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    as_mailer(db)
    transport = MemoryTransport()
    result = run(db, transport, dry_run=True)
    assert transport.sent == []
    assert deliveries(db) == []
    assert result.would_send == 1


def read_events(err: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in err.splitlines() if line.startswith("{")]


def test_the_daily_send_volume_is_logged_with_a_warning_near_the_free_tier(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = add_subscription(db, "a@example.com", confirmed_at=CONFIRMED)
    add_notification(db, "rasff", "2026.0001", first_seen_at=NOW - hours(2))
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, sent_at)"
        " SELECT %s, 'confirm', %s FROM generate_series(1, 249)",
        (sid, NOW - hours(1)),
    )
    as_mailer(db)
    run(db, MemoryTransport())
    events = read_events(capsys.readouterr().err)
    volume = next(e for e in events if e["event"] == "send_volume")
    assert volume["day"] == "2026-10-25"
    assert volume["total"] == 250
    assert volume["by_kind"] == {"confirm": 249, "digest": 1}
    assert any(e["event"] == "send_volume_high" for e in events)
    finished = next(e for e in events if e["event"] == "job_finished")
    assert finished["job"] == "send-digest"
    assert finished["sent"] == 1
    # No addresses in the logs.
    assert "a@example.com" not in json.dumps(events)
