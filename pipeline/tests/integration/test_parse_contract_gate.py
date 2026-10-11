"""A failed contract stops `parse` for that Source only; raw records wait in the archive."""

import json
from pathlib import Path

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.contracts import ContractViolation, SourceUnreachable
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse, replay
from openfoodalerts.probe import probe_contracts
from openfoodalerts.sources.openfda.ingest import canonical_json

FIXTURES = Path(__file__).parents[1] / "fixtures"


def archive_fixtures(db: Connection) -> None:
    page = json.loads((FIXTURES / "openfda" / "page_recent.json").read_text(encoding="utf-8"))
    for record in page["results"]:
        archive(
            db,
            source="openfda",
            kind="detail",
            source_key=record["recall_number"],
            url="https://api.fda.gov/food/enforcement.json",
            http_status=200,
            content_type="application/json",
            body=canonical_json(record),
        )
    detail = (FIXTURES / "rasff" / "details" / "881995.json").read_bytes()
    archive(
        db,
        source="rasff",
        kind="detail",
        source_key="2026.9489",
        url="https://webgate.ec.europa.eu/rasff-window/backend/public/notification/view/id/881995/en/",
        http_status=200,
        content_type="application/json",
        body=detail,
    )
    db.commit()


def counts(db: Connection) -> dict[str, int]:
    rows = db.execute(
        "SELECT s.code, count(n.id) AS n FROM sources s"
        " LEFT JOIN notifications n ON n.source_id = s.id GROUP BY s.code"
    ).fetchall()
    return {r["code"]: r["n"] for r in rows}


def fail_openfda(db: Connection) -> None:
    def broken() -> None:
        raise ContractViolation("page: results.0.recall_number: Field required")

    probe_contracts(db, {"openfda": broken})


def test_parse_skips_a_source_whose_contract_failed(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    archive_fixtures(db)
    fail_openfda(db)
    stats = parse(db)
    assert counts(db) == {"openfda": 0, "rasff": 1, "nvwa": 0}
    assert stats.extra["skipped_sources"] == ["openfda"]
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    skipped = [e for e in events if e["event"] == "parse_skipped"]
    assert [(e["source"], e["reason"]) for e in skipped] == [("openfda", "contract failed")]


def test_parse_resumes_with_the_waiting_records_after_a_passing_probe(db: Connection) -> None:
    archive_fixtures(db)
    fail_openfda(db)
    parse(db, ["openfda"])
    assert counts(db)["openfda"] == 0
    probe_contracts(db, {"openfda": lambda: None})
    stats = parse(db, ["openfda"])
    assert counts(db)["openfda"] == 6
    assert stats.new == 6
    assert "skipped_sources" not in stats.extra


def test_an_unreachable_source_does_not_block_parse(db: Connection) -> None:
    archive_fixtures(db)

    def offline() -> None:
        raise SourceUnreachable("page: HTTP 503")

    probe_contracts(db, {"openfda": offline})
    parse(db, ["openfda"])
    assert counts(db)["openfda"] == 6


def test_replay_also_skips_a_source_whose_contract_failed(db: Connection) -> None:
    archive_fixtures(db)
    parse(db)
    fail_openfda(db)
    stats = replay(db)
    assert stats.extra["skipped_sources"] == ["openfda"]
    assert stats.extra["replayed"] == 1
