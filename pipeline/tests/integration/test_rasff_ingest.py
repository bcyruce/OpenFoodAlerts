"""`ingest-rasff`: the last 14 days of the list, details only for new Notifications."""

from datetime import date

from openfoodalerts.db.connection import Connection
from openfoodalerts.sources.rasff.ingest import ingest_rasff
from tests.rasff_fake import FakeRasff

TODAY = date(2026, 10, 25)
# fixture details validated on or after 11-10-2026 (today - 14 days)
RECENT = {
    "2026.9036",
    "2026.9181",
    "2026.9335",
    "2026.9397",
    "2026.9017",
    "2026.9437",
    "2026.9458",
    "2026.9462",
    "2026.9476",
    "2026.9482",
    "2026.9489",
}


def detail_keys(db: Connection) -> list[str]:
    rows = db.execute(
        "SELECT source_key FROM raw_records WHERE kind = 'detail' ORDER BY id"
    ).fetchall()
    return [r["source_key"] for r in rows]


def test_ingest_lists_the_last_14_days_and_archives_their_details(db: Connection) -> None:
    fake = FakeRasff()
    stats = ingest_rasff(db, fake.client(), today=TODAY, items_per_page=5)
    assert {r["ecValidDateFrom"] for r in fake.list_requests} == {"11-10-2026 00:00:00"}
    assert len(fake.list_requests) == 3
    assert set(detail_keys(db)) == RECENT
    assert stats.new == len(RECENT)


def test_a_rerun_fetches_only_newly_published_notifications(db: Connection) -> None:
    fake = FakeRasff()
    newest = fake.details.pop(881995)
    ingest_rasff(db, fake.client(), today=TODAY)
    fake.serve(newest)
    fake.detail_requests.clear()
    stats = ingest_rasff(db, fake.client(), today=TODAY)
    assert fake.detail_requests == [881995]
    assert stats.extra["skipped"] == len(RECENT) - 1
    assert sorted(detail_keys(db)) == sorted(RECENT)
    fake.detail_requests.clear()
    stats = ingest_rasff(db, fake.client(), today=TODAY)
    assert fake.detail_requests == []
    assert len(detail_keys(db)) == len(RECENT)
    row = db.execute("SELECT last_success_at FROM sources WHERE code = 'rasff'").fetchone()
    assert row is not None and row["last_success_at"] is not None


def test_max_details_caps_a_trial_run(db: Connection) -> None:
    fake = FakeRasff()
    stats = ingest_rasff(db, fake.client(), today=TODAY, max_details=4)
    assert len(fake.detail_requests) == 4
    assert stats.extra["capped"] is True
