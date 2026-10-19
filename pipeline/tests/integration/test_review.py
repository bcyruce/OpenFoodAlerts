"""Human review (ticket 20): approve / correct a current AI classification, and the
derived tables (notification_hazards for T1) follow the effective value."""

from datetime import UTC, datetime
from typing import Any

import pytest

from openfoodalerts.classify.job import ClassifyRun, classify_notifications
from openfoodalerts.classify.model import ModelRequest, ModelResponse
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.review import ReviewError, approve, correct
from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 25, 9, 30, tzinfo=UTC)
TASK = HazardCategoryTask(load_taxonomy(default_taxonomy_path()))
# RASFF Hazard category ids (db/seed/rasff/hazard_categories.json)
ALLERGENS, FOOD_ADDITIVES = 21798, 21792
REASON = "Undeclared milk and Yellow 5 in cookies"


class Fixed:
    """A model that always gives the same answer."""

    model = "fake"

    def __init__(self, category: str = "allergens", confidence: str = "low") -> None:
        self.output = {
            "evidence_span": "Undeclared milk",
            "category": category,
            "confidence": confidence,
        }

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(self.output)


def classify(db: Connection, model: Fixed | None = None) -> ClassifyRun:
    classifier = model or Fixed()
    return classify_notifications(
        db,
        task=TASK,
        prompt=load_prompt(TASK.name),
        model=classifier.model,
        make_classifier=lambda: classifier,
    )


def notification(db: Connection, key: str = "a", reason: str = REASON) -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason)
    db.execute("UPDATE notifications SET product_text = 'Cookies' WHERE id = %s", (nid,))
    db.commit()
    return nid


def classification(db: Connection, nid: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT id, review_status, reviewed_value, reviewed_at FROM ai_classifications"
        " WHERE notification_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
        (nid,),
    ).fetchone()
    assert row is not None
    return row


def ai_hazards(db: Connection, nid: int) -> list[tuple[int, int, bool]]:
    rows = db.execute(
        "SELECT c.rasff_id, h.ai_classification_id, h.is_primary FROM notification_hazards h"
        " JOIN hazard_categories c ON c.id = h.hazard_category_id"
        " WHERE h.notification_id = %s AND h.provenance = 'ai' ORDER BY 1",
        (nid,),
    ).fetchall()
    return [(r["rasff_id"], r["ai_classification_id"], r["is_primary"]) for r in rows]


def queued(db: Connection) -> list[int]:
    return [r["classification_id"] for r in db.execute("SELECT * FROM review_queue").fetchall()]


def test_approving_keeps_the_model_value_and_leaves_the_queue(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    assert queued(db) == [cid]

    approve(db, TASK, cid, now=LATER)

    row = classification(db, nid)
    assert (row["review_status"], row["reviewed_value"], row["reviewed_at"]) == (
        "approved",
        {"category": "allergens"},
        LATER,
    )
    assert queued(db) == []
    assert ai_hazards(db, nid) == [(ALLERGENS, cid, True)]


def test_a_correction_replaces_the_ai_primary_hazard(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]

    result = correct(db, TASK, cid, {"category": "food additives and flavourings"}, now=LATER)

    row = classification(db, nid)
    assert (row["review_status"], row["reviewed_value"], row["reviewed_at"]) == (
        "corrected",
        {"category": "food additives and flavourings"},
        LATER,
    )
    assert result.value == {"category": "food additives and flavourings"}
    assert ai_hazards(db, nid) == [(FOOD_ADDITIVES, cid, True)]
    assert queued(db) == []


def test_a_correction_to_the_model_value_is_an_approval(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    result = correct(db, TASK, cid, {"category": "allergens"}, now=LATER)
    row = classification(db, nid)
    assert (result.review_status, row["review_status"], row["reviewed_value"]) == (
        "approved",
        "approved",
        {"category": "allergens"},
    )


def test_a_correction_to_other_removes_the_ai_primary_hazard(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    result = correct(db, TASK, cid, {"category": "other"}, now=LATER)
    assert classification(db, nid)["reviewed_value"] == {"category": "other"}
    assert (result.value, result.derived.unmapped) == ({"category": "other"}, 1)
    assert ai_hazards(db, nid) == []


def test_a_reviewer_abstain_removes_the_ai_primary_hazard(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    result = correct(db, TASK, cid, None, now=LATER)
    row = classification(db, nid)
    assert row["review_status"] == "corrected"
    assert row["reviewed_value"]["abstain_reason"] == "reviewer_abstained"
    assert result.value is None
    assert ai_hazards(db, nid) == []
    assert queued(db) == []


def test_a_correction_gives_an_abstained_result_its_hazard(db: Connection) -> None:
    nid = notification(db)
    classify(db, Fixed(category="abstain"))
    cid = classification(db, nid)["id"]
    assert ai_hazards(db, nid) == []
    correct(db, TASK, cid, {"category": "allergens"}, now=LATER)
    assert ai_hazards(db, nid) == [(ALLERGENS, cid, True)]


def test_approving_an_abstain_keeps_it_without_a_hazard(db: Connection) -> None:
    nid = notification(db)
    classify(db, Fixed(category="abstain"))
    cid = classification(db, nid)["id"]
    result = approve(db, TASK, cid, now=LATER)
    assert classification(db, nid)["review_status"] == "approved"
    assert result.value is None
    assert ai_hazards(db, nid) == []
    assert queued(db) == []


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"category": "space dust"}, "not a valid hazard_category value"),
        ({"category": None}, "not a valid hazard_category value"),
        ({"category": "allergens", "hazard": "milk"}, "has no field hazard"),
    ],
)
def test_an_invalid_correction_is_refused_and_writes_nothing(
    db: Connection, value: dict[str, Any], message: str
) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    with pytest.raises(ReviewError, match=message):
        correct(db, TASK, cid, value, now=LATER)
    db.rollback()
    assert classification(db, nid)["review_status"] == "unreviewed"
    assert ai_hazards(db, nid) == [(ALLERGENS, cid, True)]


def test_only_the_current_result_can_be_reviewed(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    old = classification(db, nid)["id"]
    db.execute("UPDATE notifications SET hazard_text = 'Undeclared milk' WHERE id = %s", (nid,))
    db.commit()
    classify(db)
    new = classification(db, nid)["id"]
    assert new != old
    with pytest.raises(ReviewError, match="superseded"):
        approve(db, TASK, old, now=LATER)
    with pytest.raises(ReviewError, match="no AI classification"):
        approve(db, TASK, new + 100, now=LATER)


def test_a_review_needs_the_task_of_the_row(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]

    class Other(HazardCategoryTask):
        name = "product_category"

    with pytest.raises(ReviewError, match="is hazard_category, not product_category"):
        approve(db, Other(TASK.taxonomy), cid, now=LATER)


def test_repeating_a_review_changes_nothing(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    value = {"category": "food additives and flavourings"}
    assert correct(db, TASK, cid, value, now=LATER).changed
    again = correct(db, TASK, cid, value, now=datetime(2026, 10, 26, tzinfo=UTC))
    assert not again.changed
    assert classification(db, nid)["reviewed_at"] == LATER
    assert ai_hazards(db, nid) == [(FOOD_ADDITIVES, cid, True)]


def test_a_later_review_replaces_an_earlier_one(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    correct(db, TASK, cid, {"category": "food additives and flavourings"}, now=T)
    approve(db, TASK, cid, now=LATER)
    row = classification(db, nid)
    assert (row["review_status"], row["reviewed_value"], row["reviewed_at"]) == (
        "approved",
        {"category": "allergens"},
        LATER,
    )
    assert ai_hazards(db, nid) == [(ALLERGENS, cid, True)]


def test_classifying_again_keeps_a_correction_of_the_same_input(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    cid = classification(db, nid)["id"]
    correct(db, TASK, cid, {"category": "food additives and flavourings"}, now=LATER)
    result = classify(db)
    assert (result.done, result.classified) == (1, 0)
    assert ai_hazards(db, nid) == [(FOOD_ADDITIVES, cid, True)]


def test_a_changed_input_gets_a_new_unreviewed_result(db: Connection) -> None:
    nid = notification(db)
    classify(db)
    old = classification(db, nid)["id"]
    correct(db, TASK, old, {"category": "food additives and flavourings"}, now=LATER)
    db.execute("UPDATE notifications SET hazard_text = 'Undeclared milk' WHERE id = %s", (nid,))
    db.commit()

    classify(db)

    new = classification(db, nid)
    assert new["id"] != old and new["review_status"] == "unreviewed"
    # the model's value of the new input is shown; the old review stays as history
    assert ai_hazards(db, nid) == [(ALLERGENS, new["id"], True)]
    kept = db.execute(
        "SELECT review_status, reviewed_value FROM ai_classifications WHERE id = %s", (old,)
    ).fetchone()
    assert kept == {
        "review_status": "corrected",
        "reviewed_value": {"category": "food additives and flavourings"},
    }
    assert queued(db) == [new["id"]]
