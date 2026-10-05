"""Notification versions (ticket 03), driven through the openFDA archive -> parse path."""

import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse, replay
from openfoodalerts.sources.openfda.ingest import canonical_json

KEY = "H-0015-2027"


@pytest.fixture
def recall(fixtures_dir: Path) -> dict[str, Any]:
    body = json.loads((fixtures_dir / "openfda" / "page_recent.json").read_text(encoding="utf-8"))
    return next(r for r in body["results"] if r["recall_number"] == KEY)


def observe(db: Connection, record: dict[str, Any]) -> None:
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
    db.commit()
    parse(db, ["openfda"])


def versions(db: Connection) -> list[dict[str, Any]]:
    return db.execute(
        """
        SELECT v.version, v.changed_fields, v.is_substantial, v.raw_record_id, v.observed_at
        FROM notification_versions v JOIN notifications n ON n.id = v.notification_id
        WHERE n.source_key = %s ORDER BY v.version
        """,
        (KEY,),
    ).fetchall()


def notification(db: Connection) -> dict[str, Any]:
    row = db.execute("SELECT * FROM notifications WHERE source_key = %s", (KEY,)).fetchone()
    assert row is not None
    return row


def test_first_observation_is_version_1(db: Connection, recall: dict[str, Any]) -> None:
    observe(db, recall)
    [v1] = versions(db)
    assert v1["version"] == 1
    assert v1["is_substantial"] is False
    n = notification(db)
    assert n["current_version"] == 1
    assert n["first_seen_at"] == v1["observed_at"]


def test_classification_upgrade_is_substantial(db: Connection, recall: dict[str, Any]) -> None:
    observe(db, recall)
    recall["classification"] = "Class I"
    observe(db, recall)
    v2 = versions(db)[1]
    assert v2["changed_fields"] == {"risk_official": {"old": "Class II", "new": "Class I"}}
    assert v2["is_substantial"] is True
    n = notification(db)
    assert n["current_version"] == 2
    assert n["last_changed_at"] == v2["observed_at"]


def test_classification_downgrade_is_not_substantial(
    db: Connection, recall: dict[str, Any]
) -> None:
    observe(db, recall)
    recall["classification"] = "Class III"
    observe(db, recall)
    assert versions(db)[1]["is_substantial"] is False


def test_distribution_change_is_substantial(db: Connection, recall: dict[str, Any]) -> None:
    observe(db, recall)
    recall["distribution_pattern"] = "Texas and Oklahoma"
    observe(db, recall)
    v2 = versions(db)[1]
    assert v2["changed_fields"] == {
        "source_fields.distribution_pattern": {"old": "Texas", "new": "Texas and Oklahoma"}
    }
    assert v2["is_substantial"] is True


def test_termination_is_not_substantial(db: Connection, recall: dict[str, Any]) -> None:
    observe(db, recall)
    recall["status"] = "Terminated"
    recall["termination_date"] = "20261101"
    observe(db, recall)
    v2 = versions(db)[1]
    assert set(v2["changed_fields"]) == {"status_official", "source_fields.termination_date"}
    assert v2["is_substantial"] is False


def test_raw_change_without_field_change_adds_no_version(
    db: Connection, recall: dict[str, Any]
) -> None:
    observe(db, recall)
    recall["openfda"] = {"unused": ["x"]}  # archived, but not a normalized field
    observe(db, recall)
    assert len(versions(db)) == 1


def test_replay_rebuilds_the_same_history_without_network(
    db: Connection, recall: dict[str, Any]
) -> None:
    observe(db, recall)
    recall["classification"] = "Class I"
    observe(db, recall)
    recall["status"] = "Terminated"
    observe(db, recall)
    before = (versions(db), notification(db))
    replay(db, ["openfda"])
    first = (versions(db), notification(db))
    replay(db, ["openfda"])
    assert (versions(db), notification(db)) == first
    assert [v["changed_fields"] for v in first[0]] == [v["changed_fields"] for v in before[0]]
    assert first[1]["id"] == before[1]["id"]
