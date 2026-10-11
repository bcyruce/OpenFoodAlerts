"""`refresh-rasff`: re-fetch recent details; changes become versions through `parse`."""

from datetime import UTC, datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.rasff.backfill import backfill_rasff
from openfoodalerts.sources.rasff.client import RasffClient
from openfoodalerts.sources.rasff.refresh import refresh_rasff
from tests.rasff_fake import FIXTURES, FakeRasff, load_detail

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
# fixture notifications validated on or after 16-10-2026 12:00 UTC (NOW - 30 days)
WITHIN_30_DAYS = {
    881011,  # 2026.9335, 20-10
    878615,  # 2026.9397, 21-10
    879014,  # 2026.9017, 22-10
    881566,  # 2026.9437, 22-10
    881658,  # 2026.9458, 23-10
    881845,  # 2026.9462, 23-10
    881936,  # 2026.9476, 23-10
    881931,  # 2026.9482, 23-10
    881995,  # 2026.9489, 23-10
}


def known(db: Connection, fake: FakeRasff) -> None:
    """Every fixture archived and parsed, as after a backfill."""
    backfill_rasff(db, fake.client())
    parse(db, ["rasff"])
    fake.detail_requests.clear()


def raw_detail_count(db: Connection) -> int:
    row = db.execute("SELECT count(*) AS n FROM raw_records WHERE kind = 'detail'").fetchone()
    assert row is not None
    return int(row["n"])


def test_refresh_refetches_only_notifications_validated_in_the_last_30_days(
    db: Connection,
) -> None:
    fake = FakeRasff()
    known(db, fake)
    before = raw_detail_count(db)
    stats = refresh_rasff(db, fake.client(), now=NOW)
    assert set(fake.detail_requests) == WITHIN_30_DAYS
    assert len(fake.detail_requests) == len(WITHIN_30_DAYS)
    assert stats.unchanged == len(WITHIN_30_DAYS)
    assert raw_detail_count(db) == before


def versions(db: Connection, key: str) -> list[dict[str, Any]]:
    return db.execute(
        """
        SELECT v.version, v.changed_fields, v.is_substantial
        FROM notification_versions v JOIN notifications n ON n.id = v.notification_id
        WHERE n.source_key = %s ORDER BY v.version
        """,
        (key,),
    ).fetchall()


def refresh_with(db: Connection, derived: str) -> list[dict[str, Any]]:
    """Known 2026.9489 is served in a later version; refresh, parse, return its versions."""
    fake = FakeRasff()
    known(db, fake)
    fake.serve(load_detail(FIXTURES / "derived" / f"{derived}.json"))
    stats = refresh_rasff(db, fake.client(), now=NOW)
    assert stats.changed == 1
    assert stats.unchanged == len(WITHIN_30_DAYS) - 1
    assert parse(db, ["rasff"]).changed == 1
    return versions(db, "2026.9489")


def test_a_new_distribution_country_after_refresh_is_a_substantial_version(
    db: Connection,
) -> None:
    v1, v2 = refresh_with(db, "881995_v2_new_distribution")
    assert v1["is_substantial"] is False
    assert v2["version"] == 2
    assert v2["is_substantial"] is True
    assert set(v2["changed_fields"]) == {"countries", "source_updated_at"}
    new = {(c["iso2"], c["role"]) for c in v2["changed_fields"]["countries"]["new"]}
    assert ("NL", "distribution") in new


def test_a_text_fix_after_refresh_only_enters_the_history(db: Connection) -> None:
    _, v2 = refresh_with(db, "881995_v2_text_fix")
    assert v2["version"] == 2
    assert v2["is_substantial"] is False
    assert set(v2["changed_fields"]) == {"title", "product_text", "source_updated_at"}


def test_a_second_refresh_without_changes_adds_nothing(db: Connection) -> None:
    fake = FakeRasff()
    known(db, fake)
    fake.serve(load_detail(FIXTURES / "derived" / "881995_v2_new_distribution.json"))
    refresh_rasff(db, fake.client(), now=NOW)
    parse(db, ["rasff"])
    before = raw_detail_count(db)
    stats = refresh_rasff(db, fake.client(), now=NOW)
    assert stats.changed == stats.new == 0
    assert raw_detail_count(db) == before
    assert parse(db, ["rasff"]).changed == 0
    assert len(versions(db, "2026.9489")) == 2


def test_max_details_refreshes_the_newest_first(db: Connection) -> None:
    fake = FakeRasff()
    known(db, fake)
    stats = refresh_rasff(db, fake.client(), now=NOW, max_details=2)
    assert fake.detail_requests == [881995, 881931]  # 23-10 16:50, 23-10 15:33
    assert stats.extra["capped"] is True
    assert stats.extra["due"] == len(WITHIN_30_DAYS)


def test_cli_runs_ingest_and_refresh_with_a_cap(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRasff()
    clients = iter([fake.client(), fake.client()])
    monkeypatch.setattr(RasffClient, "create", classmethod(lambda cls, **kw: next(clients)))
    runner = CliRunner()
    result = runner.invoke(app, ["ingest-rasff", "--max-details", "3", "--today", "2026-10-25"])
    assert result.exit_code == 0, result.output
    assert len(fake.detail_requests) == 3
    parse(db, ["rasff"])
    fake.detail_requests.clear()
    result = runner.invoke(app, ["refresh-rasff", "--max-details", "1"])
    assert result.exit_code == 0, result.output
    assert len(fake.detail_requests) <= 1
