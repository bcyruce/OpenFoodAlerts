"""`check-data`: data quality assertions after parse (spec §12.4)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.quality import CheckResult, check_data, format_report
from openfoodalerts.sources.openfda.ingest import canonical_json

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def loaded(db: Connection) -> Connection:
    """The openFDA and RASFF fixtures, archived and parsed."""
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
    for path in sorted((FIXTURES / "rasff" / "details").glob("*.json")):
        body = path.read_bytes()
        archive(
            db,
            source="rasff",
            kind="detail",
            source_key=json.loads(body)["reference"],
            url=f"https://webgate.ec.europa.eu/rasff-window/backend/public/notification/view/id/{path.stem}/en/",
            http_status=200,
            content_type="application/json",
            body=body,
        )
    db.commit()
    parse(db)
    return db


def by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {r.name: r for r in results}


def test_the_fixtures_pass_every_check(loaded: Connection) -> None:
    results = by_name(check_data(loaded, now=NOW))
    assert {n: r.ok for n, r in results.items()} == {
        "published_at": True,
        "no_future_dates": True,
        "title_and_source_url": True,
        "rasff_hazards_parsed": True,
        "rasff_hazard_coverage": True,
        "rasff_dictionaries": True,
        "openfda_recall_numbers": True,
    }


def test_a_displayed_notification_without_published_at_fails(loaded: Connection) -> None:
    loaded.execute(
        "UPDATE notifications SET published_at = NULL"
        " WHERE source_key IN ('2026.9489', '2026.0700')"
    )
    result = by_name(check_data(loaded, now=NOW))["published_at"]
    assert not result.ok
    # 2026.0700 is non-food: archived only, never shown, so not checked.
    assert result.examples == ["rasff:2026.9489"]
    assert "1 displayed Notification" in result.summary


def test_dates_in_the_future_fail(loaded: Connection) -> None:
    loaded.execute(
        "UPDATE notifications SET source_updated_at = '2026-11-02T10:00:00Z'"
        " WHERE source_key = '2026.9476'"
    )
    loaded.execute(
        "UPDATE notification_hazards SET sampling_date = '2027-10-01' WHERE notification_id ="
        " (SELECT id FROM notifications WHERE source_key = '2026.9017') AND position = 0"
    )
    result = by_name(check_data(loaded, now=NOW))["no_future_dates"]
    assert not result.ok
    assert result.examples == [
        "rasff:2026.9017 sampling_date 2027-10-01",
        "rasff:2026.9476 source_updated_at 2026-11-02",
    ]


def test_a_timestamp_a_few_minutes_ahead_is_tolerated(loaded: Connection) -> None:
    loaded.execute(
        "UPDATE notifications SET published_at = '2026-10-25T12:20:00Z'"
        " WHERE source_key = '2026.9476'"
    )
    assert by_name(check_data(loaded, now=NOW))["no_future_dates"].ok


def test_a_blank_title_or_source_url_fails(loaded: Connection) -> None:
    loaded.execute("UPDATE notifications SET title = '  ' WHERE source_key = '2026.9489'")
    loaded.execute("UPDATE notifications SET source_url = '' WHERE source_key = 'H-0015-2027'")
    result = by_name(check_data(loaded, now=NOW))["title_and_source_url"]
    assert not result.ok
    assert result.examples == ["openfda:H-0015-2027", "rasff:2026.9489"]


def test_hazards_in_the_raw_detail_but_not_in_the_database_fail(loaded: Connection) -> None:
    loaded.execute(
        "DELETE FROM notification_hazards WHERE notification_id ="
        " (SELECT id FROM notifications WHERE source_key = '2026.9458')"
    )
    result = by_name(check_data(loaded, now=NOW))["rasff_hazards_parsed"]
    assert not result.ok
    assert result.examples == ["rasff:2026.9458"]


def test_hazard_coverage_reports_the_share_without_official_hazards(loaded: Connection) -> None:
    result = by_name(check_data(loaded, now=NOW))["rasff_hazard_coverage"]
    # 11 displayed RASFF Notifications in the last 30 days; 4 have no hazard in RASFF itself.
    assert result.ok
    assert result.details["recent"] == {"notifications": 11, "without_hazard": 4}
    assert "4 of 11" in result.summary
    assert result.details["by_type"]["alert notification"] == {
        "notifications": 4,
        "without_hazard": 2,
    }


def test_hazard_coverage_fails_above_the_threshold(loaded: Connection) -> None:
    result = by_name(check_data(loaded, now=NOW, hazard_min_sample=5, hazard_max_missing=0.3))[
        "rasff_hazard_coverage"
    ]
    assert not result.ok


def test_hazard_coverage_needs_a_minimum_sample(loaded: Connection) -> None:
    result = by_name(check_data(loaded, now=NOW, hazard_min_sample=12, hazard_max_missing=0.3))[
        "rasff_hazard_coverage"
    ]
    assert result.ok


def test_unmapped_dictionary_entries_only_warn(loaded: Connection) -> None:
    loaded.execute(
        "UPDATE notifications SET source_fields = source_fields"
        """ || '{"unmapped_hazard_categories": ["space dust"]}' WHERE source_key = '2026.9489'"""
    )
    result = by_name(check_data(loaded, now=NOW))["rasff_dictionaries"]
    assert not result.ok
    assert result.severity == "warning"
    assert result.examples == ["rasff:2026.9489 hazard categories: space dust"]


def test_openfda_placeholder_recall_numbers_only_warn(loaded: Connection) -> None:
    # Real case: records "Not Yet Classified" come with recall_number "" or "N/A", so their
    # key changes once FDA assigns a number (the old Notification stays behind).
    loaded.execute("UPDATE notifications SET source_key = 'N/A' WHERE source_key = 'H-0015-2027'")
    loaded.execute("UPDATE notifications SET source_key = '' WHERE source_key = 'H-0021-2027'")
    result = by_name(check_data(loaded, now=NOW))["openfda_recall_numbers"]
    assert not result.ok
    assert result.severity == "warning"
    assert result.examples == ["openfda:", "openfda:N/A"]


def test_the_report_marks_each_check(loaded: Connection) -> None:
    loaded.execute("UPDATE notifications SET title = '' WHERE source_key = '2026.9489'")
    report = format_report(check_data(loaded, now=NOW))
    lines = report.splitlines()
    assert any(line.startswith("FAIL  title_and_source_url") for line in lines)
    assert any(line.startswith("PASS  published_at") for line in lines)
    assert "    rasff:2026.9489" in lines


def test_an_empty_database_passes(db: Connection) -> None:
    assert all(r.ok for r in check_data(db, now=NOW))
