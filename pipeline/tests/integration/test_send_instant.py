"""`ofa send-instant` (spec §5, §10.4, §10.5), run as ofa_mailer against the test database
with an in-memory transport and a fixed clock."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from openfoodalerts.db.connection import Connection, connect
from openfoodalerts.mail.digest import DigestSettings, send_digest
from openfoodalerts.mail.instant import InstantRun, send_instant
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
    add_hazard,
    add_notification,
    add_subscription,
    add_version,
    suppress,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)  # 13:00 in Amsterdam
CONFIRMED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
SALMONELLA = 21801
ALLERGENS = 21798
SUBSCRIPTION_ID = "6f1c1f0e-3a8e-4c5a-9a53-2d1c3f6a7b8c"
# Shared test vector with web/lib/subscriptions/links.test.ts (ticket 29); not a credential.
TOKEN = "wJMitkeX3x6Sd7td2o5oR6N2GOoZW6yZk2swTVSV3C8"  # gitleaks:allow
SITE = "https://openfoodalerts.nl"
SETTINGS = DigestSettings(site_url=SITE, token_secret="secret-1")
ALERT = "alert notification"


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
) -> InstantRun:
    return send_instant(db, transport, SETTINGS, now=now, dry_run=dry_run)


def subscribe(db: Connection, instant: list[str], **kw: object) -> str:
    email = str(kw.pop("email", "reader@example.com"))
    kw.setdefault("confirmed_at", CONFIRMED)
    return add_subscription(db, email, instant_sources=instant, **kw)  # type: ignore[arg-type]


def instant_rows(db: Connection) -> list[dict[str, object]]:
    return db.execute(
        "SELECT subscription_id::text AS sid, status, notification_ids, sent_at,"
        " provider_message_id FROM email_deliveries WHERE kind = 'instant' ORDER BY id"
    ).fetchall()


def keys(transport: MemoryTransport) -> list[str]:
    """The source key in each sent email's detail link, in order."""
    out = []
    for message in transport.sent:
        line = next(x for x in message.text.splitlines() if "Details on OpenFoodAlerts" in x)
        out.append(line.rsplit("/", 1)[-1])
    return out


def test_a_rasff_alert_sends_one_instant_email(db: Connection) -> None:
    subscribe(db, ["rasff"], subscription_id=SUBSCRIPTION_ID)
    alert = add_notification(
        db,
        "rasff",
        "2026.0001",
        title="Salmonella in sesame paste from Türkiye",
        notification_type=ALERT,
        risk_official="serious",
        first_seen_at=NOW - hours(1),
    )
    add_notification(
        db,
        "rasff",
        "2026.0002",
        notification_type="information notification for attention",
        first_seen_at=NOW - hours(1),
    )
    add_notification(
        db,
        "rasff",
        "2026.0003",
        notification_type="border rejection notification",
        first_seen_at=NOW - hours(1),
    )
    as_mailer(db)
    transport = MemoryTransport()

    result = run(db, transport)

    [message] = transport.sent
    assert message.to == "reader@example.com"
    assert message.subject == "RASFF, alert notification: Salmonella in sesame paste from Türkiye"
    assert message.tag == "instant"
    assert message.headers == {
        "List-Unsubscribe": f"<{SITE}/api/unsubscribe?token={TOKEN}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert f"{SITE}/en/alerts/manage/{TOKEN}" in message.text
    assert f"{SITE}/api/unsubscribe?token={TOKEN}" in message.text
    assert f"{SITE}/en/n/rasff/2026.0001" in message.text
    assert "https://example.test/rasff/2026.0001" in message.text
    [row] = instant_rows(db)
    assert row["sid"] == SUBSCRIPTION_ID
    assert row["status"] == "sent"
    assert row["notification_ids"] == [alert]
    assert row["provider_message_id"] == "memory-1"
    assert row["sent_at"] == NOW
    assert result.sent == 1


def test_fda_class_i_only(db: Connection) -> None:
    subscribe(db, ["openfda"])
    for key, classification in (("F-1", "Class I"), ("F-2", "Class II"), ("F-3", "Class III")):
        add_notification(
            db, "openfda", key, risk_official=classification, first_seen_at=NOW - hours(1)
        )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert keys(transport) == ["F-1"]
    assert transport.sent[0].subject.startswith("openFDA, Class I: ")


def test_nvwa_food_warnings_only(db: Connection) -> None:
    subscribe(db, ["nvwa"])
    add_notification(db, "nvwa", "/a/food", product_type="food", first_seen_at=NOW - hours(1))
    add_notification(db, "nvwa", "/a/toy", product_type="non-food", first_seen_at=NOW - hours(1))
    add_notification(
        db, "nvwa", "/a/pan", product_type="food contact material", first_seen_at=NOW - hours(1)
    )
    # Waiting for T5: not shown anywhere yet, so no Instant email either.
    add_notification(db, "nvwa", "/a/pending", product_type=None, first_seen_at=NOW - hours(1))
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert keys(transport) == ["food"]
    assert transport.sent[0].subject.startswith("NVWA, safety warning: ")


def test_rasff_news_and_substantial_updates_never_trigger(db: Connection) -> None:
    subscribe(db, ["rasff"])
    add_notification(
        db, "rasff", "2026.0010", notification_type="news", first_seen_at=NOW - hours(1)
    )
    known = add_notification(
        db, "rasff", "2026.0011", notification_type=ALERT, first_seen_at=NOW - timedelta(days=5)
    )
    add_version(db, known, 2, NOW - hours(1), substantial=True)
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert transport.sent == []


def test_only_sources_turned_on_for_instant_email_and_the_other_filters(db: Connection) -> None:
    subscribe(
        db,
        ["rasff"],
        filters={"sources": ["rasff", "openfda"], "hazard_categories": [SALMONELLA]},
        include_unclassified=False,
    )
    match = add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    add_hazard(db, match, SALMONELLA)
    other = add_notification(
        db, "rasff", "2026.0002", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    add_hazard(db, other, ALLERGENS)
    add_notification(
        db, "rasff", "2026.0003", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    fda = add_notification(
        db, "openfda", "F-1", risk_official="Class I", first_seen_at=NOW - hours(1)
    )
    add_hazard(db, fda, SALMONELLA)  # in the filters, but no Instant email for openFDA
    nonfood = add_notification(
        db,
        "rasff",
        "2026.0004",
        notification_type=ALERT,
        product_type="non-food",
        first_seen_at=NOW - hours(1),
    )
    add_hazard(db, nonfood, SALMONELLA)
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert keys(transport) == ["2026.0001"]


def test_subscriptions_without_instant_sources_get_nothing(db: Connection) -> None:
    subscribe(db, [])
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert transport.sent == []


def test_only_notifications_first_seen_recently_after_confirmation(db: Connection) -> None:
    subscribe(db, ["rasff"], confirmed_at=NOW - hours(30))
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(23)
    )
    # Seen before the lookback window: the Digest has it.
    add_notification(
        db, "rasff", "2026.0002", notification_type=ALERT, first_seen_at=NOW - hours(25)
    )
    # Backfilled or replayed: first seen now, but published long ago.
    add_notification(
        db,
        "rasff",
        "2012.0101",
        notification_type=ALERT,
        first_seen_at=NOW - hours(1),
        published_at=datetime(2012, 1, 3, tzinfo=UTC),
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert keys(transport) == ["2026.0001"]


def test_nothing_from_before_the_subscription_was_confirmed(db: Connection) -> None:
    subscribe(db, ["rasff"], confirmed_at=NOW - hours(2))
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(3)
    )
    add_notification(
        db, "rasff", "2026.0002", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert keys(transport) == ["2026.0002"]


def test_nothing_already_listed_in_a_digest(db: Connection) -> None:
    sid = subscribe(db, ["rasff"])
    listed = add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(8)
    )
    db.execute(
        "INSERT INTO email_deliveries (subscription_id, kind, notification_ids, sent_at, status)"
        " VALUES (%s, 'digest', %s, %s, 'sent')",
        (sid, [listed], NOW - hours(6)),
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    assert transport.sent == []


def test_never_twice(db: Connection, owner: Connection) -> None:
    subscribe(db, ["rasff"])
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    add_notification(
        owner, "rasff", "2026.0002", notification_type=ALERT, first_seen_at=NOW + hours(1)
    )
    owner.commit()
    second = run(db, transport, now=NOW + hours(2))
    assert keys(transport) == ["2026.0001", "2026.0002"]
    assert second.sent == 1
    run(db, transport, now=NOW + hours(4))
    assert len(transport.sent) == 2


class CrashAfterSending(MemoryTransport):
    """Hands the message over, then the process "dies" before recording it."""

    def send(self, message: EmailMessage) -> SendResult:
        super().send(message)
        raise SystemExit("killed")


def test_a_crash_after_sending_never_sends_twice(db: Connection) -> None:
    subscribe(db, ["rasff"])
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    crashing = CrashAfterSending()
    with pytest.raises(SystemExit):
        run(db, crashing)
    assert len(crashing.sent) == 1
    db.rollback()
    transport = MemoryTransport()
    run(db, transport, now=NOW + hours(1))
    assert transport.sent == []
    assert [r["status"] for r in instant_rows(db)] == ["sending"]


def test_an_uncertain_send_is_not_retried_but_a_failed_one_is(db: Connection) -> None:
    subscribe(db, ["rasff"], email="uncertain@example.com")
    subscribe(db, ["rasff"], email="failed@example.com")
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)

    class Flaky(MemoryTransport):
        def send(self, message: EmailMessage) -> SendResult:
            if message.to == "uncertain@example.com":
                raise DeliveryUncertain("timeout")
            raise DeliveryFailed("503")

    result = run(db, Flaky())
    assert (result.uncertain, result.failed) == (1, 1)
    transport = MemoryTransport()
    run(db, transport, now=NOW + hours(1))
    assert [m.to for m in transport.sent] == ["failed@example.com"]
    assert sorted(str(r["status"]) for r in instant_rows(db)) == ["failed", "sending", "sent"]


def test_at_most_five_a_day_the_rest_only_in_the_digest(db: Connection) -> None:
    sid = subscribe(db, ["rasff"])
    for i in range(1, 8):
        add_notification(
            db,
            "rasff",
            f"2026.000{i}",
            notification_type=ALERT,
            first_seen_at=NOW - hours(3) + timedelta(minutes=i),
        )
    as_mailer(db)
    transport = MemoryTransport()
    result = run(db, transport)
    # Oldest first.
    assert keys(transport) == [f"2026.000{i}" for i in range(1, 6)]
    assert result.capped == 2
    # Later runs that day, and after midnight, do not send the capped ones.
    run(db, transport, now=NOW + hours(5))
    run(db, transport, now=NOW + hours(12))  # 01:00 the next day in Amsterdam
    assert len(transport.sent) == 5
    assert len(instant_rows(db)) == 5

    # The next morning's Digest lists all seven; only the five sent are marked.
    digest = MemoryTransport()
    send_digest(db, digest, SETTINGS, now=datetime(2026, 10, 26, 6, 0, tzinfo=UTC))
    text = digest.sent[0].text
    assert "New (7)" in text
    assert text.count("[sent instantly]") == 5
    for i in (6, 7):
        assert f"rasff 2026.000{i}\n" in text
        assert f"rasff 2026.000{i} [sent instantly]" not in text
    del sid


def test_the_cap_is_per_subscription(db: Connection) -> None:
    subscribe(db, ["rasff"], email="a@example.com")
    subscribe(db, ["rasff"], email="b@example.com")
    for i in range(1, 7):
        add_notification(
            db, "rasff", f"2026.000{i}", notification_type=ALERT, first_seen_at=NOW - hours(1)
        )
    as_mailer(db)
    transport = MemoryTransport()
    result = run(db, transport)
    assert sorted(m.to for m in transport.sent) == ["a@example.com"] * 5 + ["b@example.com"] * 5
    assert result.capped == 2


def test_only_sendable_subscriptions_get_mail(db: Connection, owner: Connection) -> None:
    subscribe(db, ["rasff"], email="active@example.com")
    subscribe(db, ["rasff"], email="later@example.com", confirmed_at=CONFIRMED + hours(1))
    subscribe(db, ["rasff"], email="unsubscribed@example.com", status="unsubscribed")
    subscribe(db, ["rasff"], email="suppressed@example.com")
    suppress(db, "suppressed@example.com")
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
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
    assert len(instant_rows(db)) == 1


def test_chinese_subscriptions(db: Connection) -> None:
    subscribe(
        db,
        ["nvwa"],
        locale="zh",
        filters={"sources": ["nvwa"]},
        subscription_id=SUBSCRIPTION_ID,
    )
    add_notification(
        db,
        "nvwa",
        "/actueel/nieuws/2026/10/25/x",
        title="Veiligheidswaarschuwing x",
        first_seen_at=NOW - hours(1),
    )
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    transport = MemoryTransport()
    run(db, transport)
    [message] = transport.sent
    assert message.subject == "NVWA 安全警告：Veiligheidswaarschuwing x"
    assert "官方严重度：未分级" in message.text
    assert f"{SITE}/en/n/nvwa/actueel/nieuws/2026/10/25/x" in message.text
    assert f"{SITE}/zh/alerts/manage/{TOKEN}" in message.text


def test_dry_run_sends_and_records_nothing(db: Connection) -> None:
    sid = subscribe(db, ["rasff"])
    for i in range(1, 8):
        add_notification(
            db, "rasff", f"2026.000{i}", notification_type=ALERT, first_seen_at=NOW - hours(1)
        )
    as_mailer(db)
    transport = MemoryTransport()
    result = run(db, transport, dry_run=True)
    assert transport.sent == []
    assert instant_rows(db) == []
    assert result.would_send == 5
    assert result.capped == 2
    assert {s for s, _ in result.planned} == {sid}


def read_events(err: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in err.splitlines() if line.startswith("{")]


def test_logs_the_run_and_the_send_volume_without_addresses(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    subscribe(db, ["rasff"], email="a@example.com")
    add_notification(
        db, "rasff", "2026.0001", notification_type=ALERT, first_seen_at=NOW - hours(1)
    )
    as_mailer(db)
    run(db, MemoryTransport())
    events = read_events(capsys.readouterr().err)
    volume = next(e for e in events if e["event"] == "send_volume")
    assert volume["by_kind"] == {"instant": 1}
    finished = next(e for e in events if e["event"] == "job_finished")
    assert finished["job"] == "send-instant"
    assert finished["sent"] == 1
    assert "a@example.com" not in json.dumps(events)
