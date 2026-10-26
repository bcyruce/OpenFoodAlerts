"""`backfill-rasff` against a fake RASFF Window serving the real detail fixtures."""

import json

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.rasff.backfill import (
    MAX_CONSECUTIVE_DETAIL_FAILURES,
    RasffFetchError,
    backfill_rasff,
)
from openfoodalerts.sources.rasff.client import RasffClient
from tests.rasff_fake import FakeRasff


def raw_keys(db: Connection, kind: str) -> list[str]:
    rows = db.execute(
        "SELECT source_key FROM raw_records WHERE kind = %s ORDER BY id", (kind,)
    ).fetchall()
    return [r["source_key"] for r in rows]


def test_backfill_archives_every_list_page_and_detail(db: Connection) -> None:
    fake = FakeRasff()
    stats = backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.list_requests) == 4
    assert len(raw_keys(db, "list")) == 4
    assert sorted(raw_keys(db, "detail")) == sorted(d["reference"] for d in fake.details.values())
    assert stats.new == 16
    assert stats.extra["pages"] == 4
    # the list page key is the canonical request body
    assert raw_keys(db, "list")[0] == (
        'consolidated:{"parameters":{"itemsPerPage":5,"pageNumber":1}}'
    )


def test_each_list_page_logs_its_progress(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRasff()
    backfill_rasff(db, fake.client(), items_per_page=5)
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    pages = [line for line in lines if line["event"] == "rasff_list_page"]
    assert [(p["page"], p["seen"], p["total"]) for p in pages] == [
        (1, 5, 16),
        (2, 10, 16),
        (3, 15, 16),
        (4, 16, 16),
    ]
    assert pages[-1]["fetched"] == 16
    assert pages[-1]["eta_h"] == 0


def test_rerun_skips_notifications_with_an_archived_detail(db: Connection) -> None:
    fake = FakeRasff()
    backfill_rasff(db, fake.client(), items_per_page=5, max_details=6)
    assert len(fake.detail_requests) == 6
    fake.detail_requests.clear()
    stats = backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.detail_requests) == 10
    assert stats.extra["skipped"] == 6
    assert len(raw_keys(db, "detail")) == 16


def test_interrupted_backfill_keeps_its_progress(db: Connection) -> None:
    fake = FakeRasff()
    fake.interrupt_after = 7
    with pytest.raises(KeyboardInterrupt):
        backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(raw_keys(db, "detail")) == 7
    fake.interrupt_after = None
    fake.detail_requests.clear()
    backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.detail_requests) == 9
    assert len(set(raw_keys(db, "detail"))) == len(raw_keys(db, "detail")) == 16


def test_a_missing_detail_is_reported_and_retried_next_run(db: Connection) -> None:
    fake = FakeRasff()
    fake.missing = {881995}
    stats = backfill_rasff(db, fake.client(), items_per_page=50)
    assert stats.extra["missing"] == 1
    assert "2026.9489" not in raw_keys(db, "detail")
    fake.missing.clear()
    fake.detail_requests.clear()
    backfill_rasff(db, fake.client(), items_per_page=50)
    assert fake.detail_requests == [881995]


def test_a_detail_that_keeps_failing_is_skipped_and_retried_next_run(db: Connection) -> None:
    fake = FakeRasff()
    fake.broken = {881995}  # some RASFF details answer HTTP 500 for good
    stats = backfill_rasff(db, fake.client(), items_per_page=50)
    assert stats.extra["failed"] == 1
    assert stats.errors == ["detail 881995: HTTP 500"]
    assert len(raw_keys(db, "detail")) == 15
    fake.broken.clear()
    fake.detail_requests.clear()
    backfill_rasff(db, fake.client(), items_per_page=50)
    assert fake.detail_requests == [881995]


def test_a_detail_with_an_empty_body_is_skipped_not_archived(db: Connection) -> None:
    fake = FakeRasff()
    fake.empty = {881995}  # RASFF once answered 200 with no body (2026-10-26)
    stats = backfill_rasff(db, fake.client(), items_per_page=50)
    assert stats.extra["failed"] == 1
    assert stats.errors == ["detail 881995: HTTP 200 with a body that is not JSON"]
    assert "2026.9489" not in raw_keys(db, "detail")


def test_many_failing_details_in_a_row_stop_the_run(db: Connection) -> None:
    fake = FakeRasff()
    fake.broken = set(fake.details)  # RASFF is down, not one bad detail
    with pytest.raises(RasffFetchError):
        backfill_rasff(db, fake.client(), items_per_page=50)
    assert len(set(fake.detail_requests)) == MAX_CONSECUTIVE_DETAIL_FAILURES  # each retried


def test_cli_runs_a_bounded_backfill_and_resumes_after_ctrl_c(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRasff()
    clients = iter([fake.client(), fake.client()])
    monkeypatch.setattr(RasffClient, "create", classmethod(lambda cls, **kw: next(clients)))
    runner = CliRunner()
    result = runner.invoke(app, ["backfill-rasff", "--max-pages", "1", "--max-details", "2"])
    assert result.exit_code == 0, result.output
    assert len(raw_keys(db, "detail")) == 2
    fake.interrupt_after = 3
    result = runner.invoke(app, ["backfill-rasff"])
    assert result.exit_code == 130
    assert "re-run" in result.output
    assert len(raw_keys(db, "detail")) == 3


def test_raw_detail_is_kept_whole_but_contacts_never_reach_parsed_tables(db: Connection) -> None:
    fake = FakeRasff()
    backfill_rasff(db, fake.client(), items_per_page=50, max_details=3)
    row = db.execute("SELECT body FROM raw_records WHERE kind = 'detail' LIMIT 1").fetchone()
    assert row is not None
    assert b"officer@authority.example" in bytes(row["body"])
    parse(db, ["rasff"])
    dump = db.execute(
        "SELECT string_agg(to_jsonb(n)::text, '') AS t FROM notifications n"
    ).fetchone()
    assert dump is not None
    assert "officer@authority.example" not in dump["t"]
    assert "contactPerson" not in dump["t"]
