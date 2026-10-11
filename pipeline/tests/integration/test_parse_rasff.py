"""RASFF archive -> parse -> Notifications with Hazards, categories, countries and measures."""

import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse, replay

DETAILS = Path(__file__).parents[1] / "fixtures" / "rasff" / "details"


def load(notif_id: int) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((DETAILS / f"{notif_id}.json").read_text(encoding="utf-8"))
    return body


def put(db: Connection, body: dict[str, Any]) -> None:
    archive(
        db,
        source="rasff",
        kind="detail",
        source_key=body["reference"],
        url=f"https://example.test/notification/view/id/{body['id']}/en/",
        http_status=200,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False).encode(),
    )
    db.commit()


def notification(db: Connection, key: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM notifications WHERE source_key = %s", (key,)).fetchone()
    assert row is not None
    return row


def hazards(db: Connection, key: str) -> list[dict[str, Any]]:
    return db.execute(
        """
        SELECT h.hazard_name, c.name_en AS category, h.is_primary, h.provenance
        FROM notification_hazards h
        JOIN notifications n ON n.id = h.notification_id
        LEFT JOIN hazard_categories c ON c.id = h.hazard_category_id
        WHERE n.source_key = %s ORDER BY h.position
        """,
        (key,),
    ).fetchall()


def countries(db: Connection, key: str, role: str) -> list[str]:
    rows = db.execute(
        """
        SELECT c.country_iso2 FROM notification_countries c
        JOIN notifications n ON n.id = c.notification_id
        WHERE n.source_key = %s AND c.role = %s ORDER BY 1
        """,
        (key, role),
    ).fetchall()
    return [r["country_iso2"] for r in rows]


def versions(db: Connection, key: str) -> list[dict[str, Any]]:
    return db.execute(
        """
        SELECT v.version, v.changed_fields, v.is_substantial
        FROM notification_versions v JOIN notifications n ON n.id = v.notification_id
        WHERE n.source_key = %s ORDER BY v.version
        """,
        (key,),
    ).fetchall()


def add_distribution(body: dict[str, Any], code: str, name: str) -> None:
    body["organizationFlags"].append(
        {
            "organization": {"description": name, "code": code},
            "notificationFlags": [{"flagType": "DISTRIBUTION"}],
        }
    )


def test_a_new_distribution_country_is_a_substantial_new_version(db: Connection) -> None:
    body = load(881995)
    put(db, body)
    parse(db, ["rasff"])
    add_distribution(body, "NL", "Netherlands")
    put(db, body)
    stats = parse(db, ["rasff"])
    assert stats.changed == 1
    v2 = versions(db, "2026.9489")[1]
    assert v2["is_substantial"] is True
    assert set(v2["changed_fields"]) == {"countries"}
    after = {(c["iso2"], c["role"]) for c in v2["changed_fields"]["countries"]["new"]}
    assert ("NL", "distribution") in after
    assert countries(db, "2026.9489", "distribution") == ["DE", "NL"]


def test_a_risk_decision_change_is_substantial(db: Connection) -> None:
    body = load(881995)
    put(db, body)
    parse(db, ["rasff"])
    body["risk"]["riskDecision"] = "serious"
    put(db, body)
    parse(db, ["rasff"])
    assert versions(db, "2026.9489")[1]["is_substantial"] is True


def test_other_changes_only_enter_the_history(db: Connection) -> None:
    body = load(881995)
    put(db, body)
    parse(db, ["rasff"])
    body["product"]["measures"].pop()
    body["lastUpdate"] = "24-10-2026 09:00:00"
    put(db, body)
    parse(db, ["rasff"])
    v2 = versions(db, "2026.9489")[1]
    assert set(v2["changed_fields"]) == {"measures", "source_updated_at"}
    assert v2["is_substantial"] is False
    assert db.execute("SELECT count(*) AS n FROM measures").fetchone() == {"n": 1}


CHILD_TABLES = (
    "notification_hazards",
    "notification_product_categories",
    "notification_countries",
    "measures",
)


def child_counts(db: Connection) -> dict[str, int]:
    counts = {}
    for table in CHILD_TABLES:
        row = db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
        assert row is not None
        counts[table] = int(row["n"])
    return counts


def test_all_fixtures_parse_and_reparsing_changes_nothing(db: Connection) -> None:
    for path in sorted(DETAILS.glob("*.json")):
        put(db, json.loads(path.read_text(encoding="utf-8")))
    assert parse(db, ["rasff"]).new == 16
    before = child_counts(db)
    again = parse(db, ["rasff"])
    assert (again.new, again.changed, again.unchanged) == (0, 0, 0)
    for path in sorted(DETAILS.glob("*.json")):  # same content, fetched again
        put(db, json.loads(path.read_text(encoding="utf-8")) | {"_refetch": 1})
    third = parse(db, ["rasff"])
    assert (third.new, third.changed, third.unchanged) == (0, 0, 16)
    assert child_counts(db) == before


def test_replay_rebuilds_children_and_keeps_ids(db: Connection) -> None:
    body = load(879728)
    put(db, body)
    parse(db, ["rasff"])
    add_distribution(body, "DE", "Germany")
    put(db, body)
    parse(db, ["rasff"])
    ids = db.execute("SELECT id FROM notifications").fetchall()
    before = child_counts(db)
    replay(db, ["rasff"])
    assert db.execute("SELECT id FROM notifications").fetchall() == ids
    assert child_counts(db) == before
    assert [v["version"] for v in versions(db, "2026.9181")] == [1, 2]
    assert countries(db, "2026.9181", "distribution") == ["BE", "DE", "FR"]


def test_ai_child_rows_survive_a_parser_rewrite(db: Connection) -> None:
    body = load(881995)
    put(db, body)
    parse(db, ["rasff"])
    db.execute(
        """
        INSERT INTO notification_hazards (notification_id, hazard_category_id, provenance)
        SELECT n.id, c.id, 'ai' FROM notifications n, hazard_categories c
        WHERE c.name_en = 'allergens'
        """
    )
    db.commit()
    body["product"]["hazards"].pop()
    put(db, body)
    parse(db, ["rasff"])
    rows = db.execute(
        "SELECT provenance, count(*) AS n FROM notification_hazards GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert rows == [{"provenance": "ai", "n": 1}, {"provenance": "official", "n": 1}]


@pytest.mark.parametrize("notif_id", [852666, 819084])
def test_non_food_is_archived_as_non_food(db: Connection, notif_id: int) -> None:
    body = load(notif_id)
    put(db, body)
    parse(db, ["rasff"])
    n = notification(db, body["reference"])
    assert (n["product_type"], n["product_type_provenance"]) == ("non-food", "official")


def test_parse_writes_the_notification_and_its_child_records(db: Connection) -> None:
    put(db, load(881995))
    stats = parse(db, ["rasff"])
    assert stats.new == 1
    n = notification(db, "2026.9489")
    assert n["source_ref"] == "881995"
    assert n["parser_version"] == "rasff-1"
    assert n["search_tsv"] is not None  # see test_search_tsv.py
    assert hazards(db, "2026.9489") == [
        {
            "hazard_name": "glycidyl esters",
            "category": "industrial contaminants",
            "is_primary": None,
            "provenance": "official",
        },
        {
            "hazard_name": "3-monochlor-1,2-propanediol (3-MCPD)",
            "category": "industrial contaminants",
            "is_primary": None,
            "provenance": "official",
        },
    ]
    assert countries(db, "2026.9489", "origin") == ["CN"]
    assert countries(db, "2026.9489", "notifying") == ["DE"]
    category = db.execute(
        """
        SELECT p.name_en FROM notification_product_categories x
        JOIN product_categories p ON p.id = x.product_category_id
        """
    ).fetchall()
    assert category == [{"name_en": "prepared dishes and snacks"}]
    measures = db.execute(
        "SELECT country_iso2, action_text FROM measures ORDER BY position"
    ).fetchall()
    assert measures == [
        {"country_iso2": "DE", "action_text": "informing authorities"},
        {"country_iso2": "DE", "action_text": "recall from consumer"},
    ]
