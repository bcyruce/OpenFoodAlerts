"""Derived tables from the current AI classification (`classify.derived`): one function
computes the effective value (a corrected review wins) and rewrites the task's rows."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from openfoodalerts.classify.derived import apply_current, effective_value
from openfoodalerts.classify.tasks import make_task
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
TAXONOMY = load_taxonomy(default_taxonomy_path())
HASH = "a" * 64


def task(name: str) -> Any:
    return make_task(name, TAXONOMY)


def classification(
    db: Connection,
    nid: int,
    name: str,
    value: dict[str, Any],
    *,
    abstained: bool = False,
    at: datetime = T,
    prompt_version: str = "v1",
) -> int:
    row = db.execute(
        "INSERT INTO ai_classifications (notification_id, task, value, confidence, abstained,"
        " model, prompt_version, schema_version, input_hash, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'fake', %s, '1', %s, %s) RETURNING id",
        (nid, name, Jsonb(value), None if abstained else "high", abstained, prompt_version,
         HASH, at),
    ).fetchone()  # fmt: skip
    assert row is not None
    return int(row["id"])


def correct(db: Connection, cid: int, reviewed: dict[str, Any]) -> None:
    db.execute(
        "UPDATE ai_classifications SET review_status = 'corrected', reviewed_value = %s,"
        " reviewed_at = now() WHERE id = %s",
        (Jsonb(reviewed), cid),
    )


def product_categories(db: Connection, nid: int) -> list[tuple[str, str, int | None]]:
    return [
        (r["name_en"], r["provenance"], r["ai_classification_id"])
        for r in db.execute(
            "SELECT c.name_en, p.provenance, p.ai_classification_id"
            " FROM notification_product_categories p"
            " JOIN product_categories c ON c.id = p.product_category_id"
            " WHERE p.notification_id = %s ORDER BY p.id",
            (nid,),
        ).fetchall()
    ]


def test_the_effective_value_is_the_reviewed_value_only_when_corrected() -> None:
    value = {"category": "allergens"}
    assert effective_value(value, "unreviewed", None) == value
    assert effective_value(value, "approved", None) == value
    assert effective_value(value, "corrected", {"category": "other"}) == {"category": "other"}


def test_t2_writes_the_ai_product_category_and_a_newer_result_replaces_it(
    db: Connection,
) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    first = classification(db, nid, "product_category", {"category": "pet food"})
    assert apply_current(db, task("product_category"), nid).written == 1
    assert product_categories(db, nid) == [("pet food", "ai", first)]
    newer = classification(
        db, nid, "product_category", {"category": "confectionery"}, at=T + timedelta(1),
        prompt_version="v2",
    )  # fmt: skip
    apply_current(db, task("product_category"), nid)
    assert product_categories(db, nid) == [("confectionery", "ai", newer)]
    # an abstained current result leaves no AI row
    classification(
        db, nid, "product_category", {"category": None, "abstain_reason": "model_abstained"},
        abstained=True, at=T + timedelta(2), prompt_version="v3",
    )  # fmt: skip
    assert apply_current(db, task("product_category"), nid).written == 0
    assert product_categories(db, nid) == []


def test_a_corrected_review_is_what_the_derived_row_shows(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    cid = classification(
        db, nid, "product_category", {"category": None, "abstain_reason": "model_abstained"},
        abstained=True,
    )  # fmt: skip
    correct(db, cid, {"category": "herbs and spices"})
    apply_current(db, task("product_category"), nid)
    assert product_categories(db, nid) == [("herbs and spices", "ai", cid)]


def test_t3_writes_its_own_hazard_row_next_to_t1s(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    t1 = classification(db, nid, "hazard_category", {"category": "allergens"})
    t3 = classification(db, nid, "hazard", {"hazard": "Undeclared milk"})
    apply_current(db, task("hazard_category"), nid)
    assert apply_current(db, task("hazard"), nid).written == 1
    apply_current(db, task("hazard_category"), nid)  # T1 again leaves T3's row alone
    rows = db.execute(
        "SELECT position, hazard_name, hazard_category_id IS NOT NULL AS has_category,"
        " is_primary, provenance, ai_classification_id FROM notification_hazards"
        " WHERE notification_id = %s ORDER BY position",
        (nid,),
    ).fetchall()
    assert rows == [
        {"position": 0, "hazard_name": None, "has_category": True, "is_primary": True,
         "provenance": "ai", "ai_classification_id": t1},
        {"position": 1, "hazard_name": "Undeclared milk", "has_category": False,
         "is_primary": None, "provenance": "ai", "ai_classification_id": t3},
    ]  # fmt: skip


def test_t4_writes_an_origin_country_and_unknown_writes_none(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    cid = classification(db, nid, "origin_country", {"country": "IT"})
    assert apply_current(db, task("origin_country"), nid).written == 1
    rows = db.execute(
        "SELECT country_iso2, role, provenance, ai_classification_id FROM notification_countries"
        " WHERE notification_id = %s",
        (nid,),
    ).fetchall()
    assert rows == [
        {"country_iso2": "IT", "role": "origin", "provenance": "ai", "ai_classification_id": cid}
    ]
    classification(
        db, nid, "origin_country", {"country": "unknown"}, at=T + timedelta(1), prompt_version="v2"
    )
    assert apply_current(db, task("origin_country"), nid).written == 0
    assert db.execute(
        "SELECT count(*) AS n FROM notification_countries WHERE notification_id = %s", (nid,)
    ).fetchone() == {"n": 0}
    # a corrected value that is not a known country is not written
    later = classification(
        db, nid, "origin_country", {"country": "IT"}, at=T + timedelta(2), prompt_version="v3"
    )
    correct(db, later, {"country": "ZZ"})
    applied = apply_current(db, task("origin_country"), nid)
    assert (applied.written, applied.unmapped) == (0, 1)


def product_type(db: Connection, nid: int) -> tuple[str | None, str]:
    row = db.execute(
        "SELECT product_type, product_type_provenance FROM notifications WHERE id = %s", (nid,)
    ).fetchone()
    assert row is not None
    return row["product_type"], row["product_type_provenance"]


def test_t5_sets_the_product_type_and_an_abstain_counts_as_food(db: Connection) -> None:
    pending = add_notification(db, "nvwa", "/a", first_seen_at=T, product_type=None)
    classification(db, pending, "product_type", {"product_type": "food contact material"})
    assert apply_current(db, task("product_type"), pending).written == 1
    assert product_type(db, pending) == ("food contact material", "ai")
    unsure = add_notification(db, "nvwa", "/b", first_seen_at=T, product_type=None)
    classification(
        db, unsure, "product_type", {"product_type": None, "abstain_reason": "model_abstained"},
        abstained=True,
    )  # fmt: skip
    apply_current(db, task("product_type"), unsure)
    assert product_type(db, unsure) == ("food", "ai")


def test_t5_never_overrides_a_rule_or_official_product_type(db: Connection) -> None:
    ruled = add_notification(db, "nvwa", "/a", first_seen_at=T, product_type="non-food")
    classification(db, ruled, "product_type", {"product_type": "food"})
    assert apply_current(db, task("product_type"), ruled).written == 0
    assert product_type(db, ruled) == ("non-food", "official")


def test_without_a_classification_nothing_is_written(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    assert apply_current(db, task("product_category"), nid).written == 0
