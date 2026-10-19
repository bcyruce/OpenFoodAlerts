"""A Product type set by T5 (provenance ai) survives re-parsing while the rules still
cannot decide; once the rules decide, the rule wins (ticket 17)."""

import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse, replay
from openfoodalerts.sources.openfda.ingest import canonical_json

pytestmark = pytest.mark.db
KEY = "H-0015-2027"


@pytest.fixture
def recall(fixtures_dir: Path) -> dict[str, Any]:
    body = json.loads((fixtures_dir / "openfda" / "page_recent.json").read_text(encoding="utf-8"))
    record: dict[str, Any] = next(r for r in body["results"] if r["recall_number"] == KEY)
    # feed and non-food keywords at once: the rules leave it to T5
    record["product_description"] = "Dog treats gift box with a dog shampoo sample"
    return record


def observe(db: Connection, record: dict[str, Any]) -> None:
    archive(
        db,
        source="openfda",
        kind="detail",
        source_key=KEY,
        url="https://api.fda.gov/food/enforcement.json",
        http_status=200,
        content_type="application/json",
        body=canonical_json(record),
    )
    db.commit()
    parse(db, ["openfda"])


def state(db: Connection) -> tuple[str | None, str, int]:
    row = db.execute(
        "SELECT product_type, product_type_provenance, current_version FROM notifications"
        " WHERE source_key = %s",
        (KEY,),
    ).fetchone()
    assert row is not None
    return row["product_type"], row["product_type_provenance"], row["current_version"]


def t5_says(db: Connection, product_type: str) -> None:
    db.execute(
        "UPDATE notifications SET product_type = %s, product_type_provenance = 'ai'"
        " WHERE source_key = %s",
        (product_type, KEY),
    )
    db.commit()


def test_an_ai_product_type_survives_a_change_and_a_replay(
    db: Connection, recall: dict[str, Any]
) -> None:
    observe(db, recall)
    assert state(db) == (None, "pending", 1)
    t5_says(db, "feed")
    recall["reason_for_recall"] = "Undeclared peanut in the treats."
    observe(db, recall)
    assert state(db) == ("feed", "ai", 2)
    [changed] = db.execute(
        "SELECT changed_fields FROM notification_versions WHERE version = 2"
    ).fetchall()
    assert set(changed["changed_fields"]) == {"hazard_text"}  # not product_type
    replay(db, ["openfda"])
    assert state(db)[:2] == ("feed", "ai")


def test_once_the_rules_decide_the_rule_wins(db: Connection, recall: dict[str, Any]) -> None:
    observe(db, recall)
    t5_says(db, "non-food")
    recall["product_description"] = "Dog treats gift box"
    observe(db, recall)
    assert state(db) == ("feed", "rule", 2)
