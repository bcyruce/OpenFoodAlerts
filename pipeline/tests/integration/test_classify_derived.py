"""T2-T5 derived rows from the current AI classification (`classify.effective.rederive`):
the effective value (a corrected review wins) rewrites the task's own rows only."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from openfoodalerts.classify.effective import rederive
from openfoodalerts.classify.review import correct as review_correct
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


def test_t2_writes_the_ai_product_category_and_a_newer_result_replaces_it(
    db: Connection,
) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    first = classification(db, nid, "product_category", {"category": "pet food"})
    assert rederive(db, task("product_category"), nid).written == 1
    assert product_categories(db, nid) == [("pet food", "ai", first)]
    newer = classification(
        db, nid, "product_category", {"category": "confectionery"}, at=T + timedelta(1),
        prompt_version="v2",
    )  # fmt: skip
    rederive(db, task("product_category"), nid)
    assert product_categories(db, nid) == [("confectionery", "ai", newer)]
    # an abstained current result leaves no AI row
    classification(
        db, nid, "product_category", {"category": None, "abstain_reason": "model_abstained"},
        abstained=True, at=T + timedelta(2), prompt_version="v3",
    )  # fmt: skip
    assert rederive(db, task("product_category"), nid).written == 0
    assert product_categories(db, nid) == []


def test_a_corrected_review_is_what_the_derived_row_shows(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    cid = classification(
        db, nid, "product_category", {"category": None, "abstain_reason": "model_abstained"},
        abstained=True,
    )  # fmt: skip
    correct(db, cid, {"category": "herbs and spices"})
    rederive(db, task("product_category"), nid)
    assert product_categories(db, nid) == [("herbs and spices", "ai", cid)]


def test_t3_writes_its_own_hazard_row_next_to_t1s(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    t1 = classification(db, nid, "hazard_category", {"category": "allergens"})
    t3 = classification(db, nid, "hazard", {"hazard": "Undeclared milk"})
    rederive(db, task("hazard_category"), nid)
    assert rederive(db, task("hazard"), nid).written == 1
    rederive(db, task("hazard_category"), nid)  # T1 again leaves T3's row alone
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
    assert rederive(db, task("origin_country"), nid).written == 1
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
    assert rederive(db, task("origin_country"), nid).written == 0
    assert db.execute(
        "SELECT count(*) AS n FROM notification_countries WHERE notification_id = %s", (nid,)
    ).fetchone() == {"n": 0}
    # a corrected value that is not a known country is not written
    later = classification(
        db, nid, "origin_country", {"country": "IT"}, at=T + timedelta(2), prompt_version="v3"
    )
    correct(db, later, {"country": "ZZ"})
    applied = rederive(db, task("origin_country"), nid)
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
    assert rederive(db, task("product_type"), pending).written == 1
    assert product_type(db, pending) == ("food contact material", "ai")
    unsure = add_notification(db, "nvwa", "/b", first_seen_at=T, product_type=None)
    classification(
        db, unsure, "product_type", {"product_type": None, "abstain_reason": "model_abstained"},
        abstained=True,
    )  # fmt: skip
    rederive(db, task("product_type"), unsure)
    assert product_type(db, unsure) == ("food", "ai")


@pytest.mark.parametrize("reason", ["refusal", "truncated", "invalid_output"])
def test_a_t5_failure_is_not_an_abstain_and_leaves_the_notification_pending(
    db: Connection, reason: str
) -> None:
    # spec §4.2: non-food is never shown, so only the model's own "cannot tell" counts as
    # food (§10.4); a refusal or broken answer must not put an unknown product on the site
    nid = add_notification(db, "nvwa", "/a", first_seen_at=T, product_type=None)
    classification(db, nid, "product_type", {"product_type": "food"})
    rederive(db, task("product_type"), nid)
    assert product_type(db, nid) == ("food", "ai")
    classification(
        db, nid, "product_type", {"product_type": None, "abstain_reason": reason},
        abstained=True, at=T + timedelta(hours=1), prompt_version="v2",
    )  # fmt: skip
    rederive(db, task("product_type"), nid)
    assert product_type(db, nid) == (None, "pending")


def test_t5_never_overrides_a_rule_or_official_product_type(db: Connection) -> None:
    ruled = add_notification(db, "nvwa", "/a", first_seen_at=T, product_type="non-food")
    classification(db, ruled, "product_type", {"product_type": "food"})
    assert rederive(db, task("product_type"), ruled).written == 0
    assert product_type(db, ruled) == ("non-food", "official")


def test_without_a_classification_nothing_is_written(db: Connection) -> None:
    nid = add_notification(db, "openfda", "F-1", first_seen_at=T)
    assert rederive(db, task("product_category"), nid).written == 0
    pending = add_notification(db, "nvwa", "/a", first_seen_at=T, product_type=None)
    rederive(db, task("product_type"), pending)
    assert product_type(db, pending) == (None, "pending")  # waiting for T5, not an abstain


def fda_text(db: Connection, key: str, product: str, reason: str) -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason)
    db.execute("UPDATE notifications SET product_text = %s WHERE id = %s", (product, nid))
    return nid


def test_review_corrections_of_t2_to_t5_rewrite_their_rows(db: Connection) -> None:
    """Ticket 20's `correct` validates through each task's `check` and re-derives."""
    nid = fda_text(db, "F-1", "Pecorino cheese wheels. Product of Italy.", "Listeria found.")
    t2 = classification(db, nid, "product_category", {"category": "pet food"})
    t3 = classification(db, nid, "hazard", {"hazard": "found"})
    t4 = classification(db, nid, "origin_country", {"country": "unknown"})
    db.commit()
    review_correct(db, task("product_category"), t2, {"category": "milk and milk products"},
                   now=T)  # fmt: skip
    review_correct(db, task("hazard"), t3, {"hazard": "Listeria"}, now=T)
    review_correct(db, task("origin_country"), t4, {"country": "IT"}, now=T)
    assert product_categories(db, nid) == [("milk and milk products", "ai", t2)]
    assert db.execute(
        "SELECT hazard_name FROM notification_hazards WHERE notification_id = %s", (nid,)
    ).fetchall() == [{"hazard_name": "Listeria"}]
    assert db.execute(
        "SELECT country_iso2 FROM notification_countries WHERE notification_id = %s", (nid,)
    ).fetchall() == [{"country_iso2": "IT"}]
    with pytest.raises(ValueError, match="evidence_not_in_input"):  # T3 stays verbatim
        review_correct(db, task("hazard"), t3, {"hazard": "listeria"}, now=T)
    with pytest.raises(ValueError, match="invalid_output"):
        review_correct(db, task("origin_country"), t4, {"country": "EUROPOL"}, now=T)


def test_a_reviewer_abstain_on_t5_counts_as_food_and_a_correction_wins(db: Connection) -> None:
    pending = add_notification(
        db, "nvwa", "/a", first_seen_at=T, product_type=None, summary_source="Pepermolen."
    )
    cid = classification(db, pending, "product_type", {"product_type": "food contact material"})
    db.commit()
    review_correct(db, task("product_type"), cid, {"product_type": "non-food"}, now=T)
    assert product_type(db, pending) == ("non-food", "ai")
    review_correct(db, task("product_type"), cid, None, now=T)
    assert product_type(db, pending) == ("food", "ai")
