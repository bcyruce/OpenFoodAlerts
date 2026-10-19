"""The review_queue view (spec §4.1, §6.5): current AI classifications that are abstained
or below the task's review threshold, not yet reviewed."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from openfoodalerts.classify.effective import effective_value
from openfoodalerts.db.connection import Connection
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
ABSTAIN: dict[str, Any] = {
    "category": None,
    "abstain_reason": "model_abstained",
    "model_output": {},
}


def add_classification(
    db: Connection,
    notification_id: int,
    *,
    category: str | None = "allergens",
    confidence: str | None = "high",
    task: str = "hazard_category",
    prompt_version: str = "v1",
    created_at: datetime = T,
    review_status: str = "unreviewed",
    reviewed_value: dict[str, Any] | None = None,
    model: str = "fake",
) -> int:
    abstained = category is None
    value = ABSTAIN if abstained else {"category": category}
    digest = hashlib.sha256(f"{notification_id}{task}{prompt_version}{model}".encode())
    row = db.execute(
        """
        INSERT INTO ai_classifications (notification_id, task, value, confidence, abstained,
            evidence_span, model, prompt_version, schema_version, taxonomy_version,
            input_hash, created_at, review_status, reviewed_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '1', 'v1-draft', %s, %s, %s, %s)
        RETURNING id
        """,
        (
            notification_id,
            task,
            Jsonb(value),
            None if abstained else confidence,
            abstained,
            None if abstained else "Undeclared milk",
            model,
            prompt_version,
            digest.hexdigest(),
            created_at,
            review_status,
            None if reviewed_value is None else Jsonb(reviewed_value),
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def notification(db: Connection, key: str, **kw: Any) -> int:
    return add_notification(
        db, "openfda", key, first_seen_at=T, hazard_text="Undeclared milk", **kw
    )


def queued(db: Connection) -> list[int]:
    rows = db.execute("SELECT classification_id FROM review_queue ORDER BY 1").fetchall()
    return [r["classification_id"] for r in rows]


def test_abstained_and_low_confidence_results_are_queued(db: Connection) -> None:
    abstained = add_classification(db, notification(db, "a"), category=None)
    low = add_classification(db, notification(db, "b"), confidence="low")
    add_classification(db, notification(db, "c"), confidence="medium")
    add_classification(db, notification(db, "d"), confidence="high")
    assert queued(db) == [abstained, low]


def test_reviewed_results_leave_the_queue(db: Connection) -> None:
    add_classification(db, notification(db, "a"), category=None, review_status="approved")
    add_classification(
        db,
        notification(db, "b"),
        confidence="low",
        review_status="corrected",
        reviewed_value={"category": "food additives"},
    )
    assert queued(db) == []


def test_only_the_current_result_of_a_notification_and_task_counts(db: Connection) -> None:
    nid = notification(db, "a")
    add_classification(db, nid, category=None, prompt_version="v1")
    newer = add_classification(
        db, nid, confidence="low", prompt_version="v2", created_at=T + timedelta(hours=1)
    )
    other_task = add_classification(db, nid, category=None, task="product_category")
    assert queued(db) == [newer, other_task]
    # a confident newer result empties the queue for that task
    add_classification(
        db, nid, confidence="high", prompt_version="v3", created_at=T + timedelta(hours=2)
    )
    assert queued(db) == [other_task]


def test_the_threshold_is_a_setting_per_task(db: Connection) -> None:
    abstained = add_classification(db, notification(db, "a"), category=None)
    low = add_classification(db, notification(db, "b"), confidence="low")
    medium = add_classification(db, notification(db, "c"), confidence="medium")
    add_classification(db, notification(db, "d"), confidence="high")
    db.execute(
        "INSERT INTO review_settings (task, min_confidence) VALUES ('hazard_category', 'high')"
    )
    assert queued(db) == [abstained, low, medium]
    db.execute("UPDATE review_settings SET min_confidence = 'low'")
    # abstains are always reviewed
    assert queued(db) == [abstained]
    db.execute("UPDATE review_settings SET task = 'product_category'")
    assert queued(db) == [abstained, low]


def test_a_threshold_must_be_a_confidence_level(db: Connection) -> None:
    with pytest.raises(errors.CheckViolation):
        db.execute("INSERT INTO review_settings (task, min_confidence) VALUES ('t', 'none')")


def test_a_queue_item_carries_the_text_to_review(db: Connection) -> None:
    nid = notification(db, "a", title="Cookies recalled", summary_source="Summary text")
    db.execute("UPDATE notifications SET product_text = 'Choc cookies' WHERE id = %s", (nid,))
    cid = add_classification(db, nid, confidence="low")
    item = db.execute("SELECT * FROM review_queue").fetchone()
    assert item is not None
    assert {k: item[k] for k in ("classification_id", "notification_id", "task", "source")} == {
        "classification_id": cid,
        "notification_id": nid,
        "task": "hazard_category",
        "source": "openfda",
    }
    assert item["reason"] == "low_confidence"
    assert item["value"] == {"category": "allergens"}
    assert (item["confidence"], item["evidence_span"]) == ("low", "Undeclared milk")
    assert (item["title"], item["product_text"], item["hazard_text"]) == (
        "Cookies recalled",
        "Choc cookies",
        "Undeclared milk",
    )
    assert item["summary_source"] == "Summary text"
    assert item["source_url"] == "https://example.test/openfda/a"


@pytest.mark.parametrize(
    ("category", "review_status", "reviewed_value"),
    [
        ("allergens", "unreviewed", None),
        (None, "unreviewed", None),
        ("allergens", "approved", {"category": "allergens"}),
        (None, "approved", ABSTAIN),
        ("allergens", "corrected", {"category": "foreign bodies"}),
        (None, "corrected", {"category": "foreign bodies"}),
        ("allergens", "corrected", {"category": None, "abstain_reason": "reviewer_abstained"}),
    ],
)
def test_the_sql_effective_value_is_the_python_one(
    db: Connection, category: str | None, review_status: str, reviewed_value: dict[str, Any]
) -> None:
    cid = add_classification(
        db,
        notification(db, "a"),
        category=category,
        review_status=review_status,
        reviewed_value=reviewed_value,
    )
    row = db.execute(
        "SELECT c.*, ai_effective_value(c) AS effective FROM ai_classifications c WHERE id = %s",
        (cid,),
    ).fetchone()
    assert row is not None
    assert row["effective"] == effective_value(row)


def test_the_queue_is_not_public(db: Connection) -> None:
    add_classification(db, notification(db, "a"), category=None)
    db.commit()
    db.execute("SET ROLE ofa_web")
    with pytest.raises(errors.InsufficientPrivilege):
        db.execute("SELECT * FROM review_queue")
    db.rollback()
    db.execute("SET ROLE ofa_pipeline")
    assert len(queued(db)) == 1
    db.rollback()
    granted = db.execute(
        "SELECT has_table_privilege('ofa_pipeline', 'review_queue', 'DELETE') AS d,"
        " has_table_privilege('ofa_mailer', 'review_queue', 'SELECT') AS m,"
        " has_table_privilege('ofa_web', 'review_settings', 'SELECT') AS w"
    ).fetchone()
    assert granted == {"d": False, "m": False, "w": False}
