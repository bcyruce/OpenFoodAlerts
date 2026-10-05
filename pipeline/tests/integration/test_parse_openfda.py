import json
from pathlib import Path
from typing import Any

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.openfda.ingest import canonical_json


def load(fixtures_dir: Path, name: str) -> list[dict[str, Any]]:
    body = json.loads((fixtures_dir / "openfda" / name).read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = body["results"]
    return results


def put(db: Connection, record: dict[str, Any]) -> None:
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


def notification(db: Connection, key: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM notifications WHERE source_key = %s", (key,)).fetchone()
    assert row is not None
    return row


def test_parses_archived_records_into_notifications(db: Connection, fixtures_dir: Path) -> None:
    for r in load(fixtures_dir, "page_recent.json") + load(fixtures_dir, "pet.json"):
        put(db, r)
    stats = parse(db, ["openfda"])
    assert stats.new == 8
    n = notification(db, "H-0015-2027")
    assert n["risk_official"] == "Class II"
    assert n["product_type"] == "food"
    assert n["parser_version"] == "openfda-3"
    assert n["source_fields"]["recalling_firm"] == "QUESO PALMITA GP LLC"
    assert notification(db, "F-1753-2019")["product_type"] == "feed"


def test_parse_is_idempotent(db: Connection, fixtures_dir: Path) -> None:
    for r in load(fixtures_dir, "page_recent.json"):
        put(db, r)
    parse(db, ["openfda"])
    again = parse(db, ["openfda"])
    assert (again.new, again.changed, again.unchanged) == (0, 0, 0)
    assert db.execute("SELECT count(*) AS n FROM notifications").fetchone() == {"n": 6}


def test_new_raw_version_updates_the_notification(db: Connection, fixtures_dir: Path) -> None:
    record = load(fixtures_dir, "page_recent.json")[0]
    put(db, record)
    parse(db, ["openfda"])
    record["status"] = "Terminated"
    put(db, record)
    stats = parse(db, ["openfda"])
    assert stats.changed == 1
    assert notification(db, record["recall_number"])["status_official"] == "Terminated"
