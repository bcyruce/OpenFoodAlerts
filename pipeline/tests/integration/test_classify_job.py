"""`ofa classify` against the test database, with the fake model: scope, idempotency,
input_hash dedupe, ai_classifications and notification_hazards rows."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.job import ClassifyRun, classify_notifications
from openfoodalerts.classify.model import (
    Classifier,
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    ModelResponse,
)
from openfoodalerts.classify.prompts import Prompt, default_prompts_dir, load_prompt
from openfoodalerts.classify.run import hash_for
from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
TAXONOMY = load_taxonomy(default_taxonomy_path())
TASK = HazardCategoryTask(TAXONOMY)
# RASFF Hazard category ids (db/seed/rasff/hazard_categories.json)
ALLERGENS, PATHOGENS, GMO_NOVEL_FOOD = 21798, 21801, 21806


class Counting:
    """The fake model, counting calls; optionally failing or answering a fixed output."""

    def __init__(self, fail_on: str | None = None, output: object = None) -> None:
        self.model = "fake"
        self.calls = 0
        self.fake = KeywordClassifier(TAXONOMY)
        self.fail_on, self.output = fail_on, output

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.fail_on and self.fail_on in request.user:
            raise ItemFailed("HTTP 400")
        if self.output is not None:
            return ModelResponse(self.output)
        return self.fake.complete(request)


def fda(db: Connection, key: str, reason: str, product: str = "Cookies", **kw: object) -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason, **kw)  # type: ignore[arg-type]
    db.execute("UPDATE notifications SET product_text = %s WHERE id = %s", (product, nid))
    return nid


def run(
    db: Connection,
    model: Classifier | None = None,
    prompt: Prompt | None = None,
    **kw: object,
) -> ClassifyRun:
    classifier = model or Counting()
    return classify_notifications(
        db,
        task=TASK,
        prompt=prompt or load_prompt(TASK.name),
        model=classifier.model,
        make_classifier=lambda: classifier,
        **kw,  # type: ignore[arg-type]
    )


def rows(db: Connection, sql: str, *params: object) -> list[dict[str, object]]:
    return db.execute(sql, params).fetchall()


def test_only_nvwa_and_fda_food_feed_and_fcm_are_classified(db: Connection) -> None:
    nvwa = add_notification(
        db, "nvwa", "/a", first_seen_at=T, title="Waarschuwing", summary_source="Bevat Listeria."
    )
    fcm = add_notification(
        db,
        "nvwa",
        "/b",
        first_seen_at=T,
        product_type="food contact material",
        summary_source="Migratie van primaire aromatische amines.",
    )
    add_notification(
        db, "nvwa", "/c", first_seen_at=T, product_type="non-food", summary_source="Listeria"
    )
    add_notification(
        db, "nvwa", "/d", first_seen_at=T, product_type=None, summary_source="Listeria"
    )
    add_notification(db, "rasff", "2026.1", first_seen_at=T, title="Listeria in cheese")
    feed = fda(db, "F-1", "Salmonella in dog food", product_type="feed")
    db.commit()
    result = run(db)
    assert result.candidates == 3 and result.classified == 3
    got = rows(db, "SELECT notification_id FROM ai_classifications ORDER BY notification_id")
    assert [r["notification_id"] for r in got] == sorted([nvwa, fcm, feed])
    assert run(db, sources=["nvwa"]).candidates == 2


def test_a_result_is_stored_with_its_provenance_and_as_the_primary_ai_hazard(
    db: Connection,
) -> None:
    nid = fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    model = Counting()
    result = run(db, model)
    assert (result.classified, result.hazards_written, model.calls) == (1, 1, 1)
    [row] = rows(db, "SELECT * FROM ai_classifications")
    snapshot = {"product_description": "Cookies", "reason_for_recall": "Undeclared peanut."}
    prompt = load_prompt(TASK.name)
    assert row["notification_id"] == nid
    assert row["task"] == "hazard_category"
    assert row["value"] == {"category": "allergens"}
    assert (row["confidence"], row["abstained"]) == ("high", False)
    assert row["evidence_span"] == "Undeclared peanut"
    assert (row["model"], row["prompt_version"], row["schema_version"]) == ("fake", "v1", "1")
    assert row["taxonomy_version"] == TAXONOMY.version
    assert row["input_hash"] == hash_for(TASK, prompt, "fake", snapshot)
    assert row["review_status"] == "unreviewed"
    [hazard] = rows(
        db,
        "SELECT h.*, c.rasff_id FROM notification_hazards h"
        " JOIN hazard_categories c ON c.id = h.hazard_category_id",
    )
    assert hazard["notification_id"] == nid
    assert (hazard["provenance"], hazard["is_primary"]) == ("ai", True)
    assert hazard["rasff_id"] == ALLERGENS
    assert hazard["ai_classification_id"] == row["id"]
    assert hazard["hazard_name"] is None


def test_a_second_run_calls_nothing_and_writes_nothing(db: Connection) -> None:
    fda(db, "F-1", "Listeria")
    fda(db, "F-2", "Undeclared milk")
    db.commit()
    assert run(db).classified == 2
    model = Counting()
    again = run(db, model)
    assert (again.candidates, again.done, again.classified, model.calls) == (2, 2, 0, 0)
    assert rows(db, "SELECT count(*) AS n FROM ai_classifications") == [{"n": 2}]
    assert rows(db, "SELECT count(*) AS n FROM notification_hazards") == [{"n": 2}]


def test_the_same_input_is_sent_once_even_across_runs(db: Connection) -> None:
    fda(db, "F-1", "Listeria", product="Brie")
    fda(db, "F-2", "Listeria", product="Brie")
    db.commit()
    model = Counting()
    result = run(db, model)
    assert model.calls == 1
    assert (result.classified, result.reused) == (1, 1)
    fda(db, "F-3", "Listeria", product="Brie")
    db.commit()
    later = Counting()
    assert run(db, later).reused == 1 and later.calls == 0
    got = rows(db, "SELECT DISTINCT input_hash, value FROM ai_classifications")
    assert len(got) == 1 and got[0]["value"] == {"category": "pathogenic micro-organisms"}
    assert rows(db, "SELECT count(*) AS n FROM notification_hazards") == [{"n": 3}]


def test_a_changed_input_gets_a_new_result_that_replaces_the_ai_hazard(db: Connection) -> None:
    nid = fda(db, "F-1", "Listeria")
    db.commit()
    run(db)
    db.execute("UPDATE notifications SET hazard_text = 'Undeclared milk' WHERE id = %s", (nid,))
    db.commit()
    assert run(db).classified == 1
    history = rows(db, "SELECT value FROM ai_classifications ORDER BY id")
    assert [r["value"]["category"] for r in history] == [  # type: ignore[index]
        "pathogenic micro-organisms",
        "allergens",
    ]
    [hazard] = rows(
        db,
        "SELECT c.rasff_id, h.ai_classification_id FROM notification_hazards h"
        " JOIN hazard_categories c ON c.id = h.hazard_category_id",
    )
    assert hazard["rasff_id"] == ALLERGENS
    assert hazard["ai_classification_id"] == max(
        r["id"]  # type: ignore[type-var]
        for r in rows(db, "SELECT id FROM ai_classifications")
    )


def test_a_new_prompt_version_classifies_again(db: Connection, tmp_path: Path) -> None:
    fda(db, "F-1", "Listeria")
    db.commit()
    run(db)
    (tmp_path / "hazard_category").mkdir()
    shutil.copy(
        default_prompts_dir() / "hazard_category" / "v1.md", tmp_path / "hazard_category" / "v2.md"
    )
    v2 = load_prompt(TASK.name, directory=tmp_path)
    assert v2.version == "v2"
    assert run(db, prompt=v2).classified == 1
    got = rows(db, "SELECT prompt_version FROM ai_classifications ORDER BY id")
    assert [r["prompt_version"] for r in got] == ["v1", "v2"]
    assert rows(db, "SELECT count(*) AS n FROM notification_hazards") == [{"n": 1}]


def test_abstains_are_stored_for_review_without_a_hazard(db: Connection) -> None:
    vague = fda(db, "F-1", "Recalled as a precaution.")
    db.commit()
    result = run(db)
    assert (result.classified, result.abstained, result.hazards_written) == (1, 1, 0)
    [row] = rows(db, "SELECT * FROM ai_classifications")
    assert row["notification_id"] == vague and row["abstained"] is True
    assert row["confidence"] is None and row["evidence_span"] is None
    assert row["value"] == {
        "category": None,
        "abstain_reason": "model_abstained",
        "model_output": {"evidence_span": "", "category": "abstain", "confidence": "low"},
    }
    assert rows(db, "SELECT count(*) AS n FROM notification_hazards") == [{"n": 0}]


def test_a_quote_that_is_not_in_the_input_is_an_abstain(db: Connection) -> None:
    fda(db, "F-1", "Listeria")
    db.commit()
    model = Counting(
        output={
            "evidence_span": "Salmonella",
            "category": "pathogenic micro-organisms",
            "confidence": "high",
        }
    )
    assert run(db, model).abstained == 1
    [row] = rows(db, "SELECT value FROM ai_classifications")
    assert row["value"]["abstain_reason"] == "evidence_not_in_input"  # type: ignore[index]


def test_merged_labels_map_to_one_category_and_other_to_none(db: Connection) -> None:
    gmo = fda(db, "F-1", "Contains unauthorised genetically modified rice")
    other = fda(db, "F-2", "Product not adequately pasteurized")
    db.commit()
    result = run(db)
    assert (result.classified, result.hazards_written, result.unmapped) == (2, 1, 1)
    [hazard] = rows(
        db,
        "SELECT h.notification_id, c.rasff_id FROM notification_hazards h"
        " JOIN hazard_categories c ON c.id = h.hazard_category_id",
    )
    assert hazard == {"notification_id": gmo, "rasff_id": GMO_NOVEL_FOOD}
    [row] = rows(db, "SELECT value FROM ai_classifications WHERE notification_id = %s", other)
    assert row["value"] == {"category": "other"}


def test_dry_run_counts_without_calling_or_writing(db: Connection) -> None:
    fda(db, "F-1", "Listeria", product="Brie")
    fda(db, "F-2", "Listeria", product="Brie")
    fda(db, "F-3", "Undeclared milk")
    db.commit()

    def unavailable() -> Classifier:
        raise AssertionError("dry run must not build a classifier")

    result = classify_notifications(
        db,
        task=TASK,
        prompt=load_prompt(TASK.name),
        model="claude-haiku-5-5",
        make_classifier=unavailable,
        dry_run=True,
    )
    assert (result.candidates, result.to_call, result.reused, result.classified) == (3, 2, 1, 0)
    assert rows(db, "SELECT count(*) AS n FROM ai_classifications") == [{"n": 0}]


def test_limit_caps_the_newest_notifications_first(db: Connection) -> None:
    old = fda(db, "F-1", "Listeria", published_at=datetime(2020, 1, 1, tzinfo=UTC))
    new = fda(db, "F-2", "Undeclared milk", published_at=datetime(2026, 10, 1, tzinfo=UTC))
    db.commit()
    assert run(db, limit=1).classified == 1
    got = rows(db, "SELECT notification_id FROM ai_classifications")
    assert got == [{"notification_id": new}]
    assert run(db, limit=1).classified == 1
    assert {
        r["notification_id"] for r in rows(db, "SELECT notification_id FROM ai_classifications")
    } == {old, new}


def test_a_failed_item_is_left_for_the_next_run_and_unavailable_stops(db: Connection) -> None:
    fda(db, "F-1", "Listeria")
    fda(db, "F-2", "Undeclared milk")
    db.commit()
    result = run(db, Counting(fail_on="milk"))
    assert (result.classified, result.failed) == (1, 1)
    assert run(db).classified == 1

    class Down:
        model = "fake"

        def complete(self, request: ModelRequest) -> ModelResponse:
            raise ClassifierUnavailable("no key")

    fda(db, "F-3", "Salmonella")
    db.commit()
    with pytest.raises(ClassifierUnavailable):
        run(db, Down())
    assert rows(db, "SELECT count(*) AS n FROM ai_classifications") == [{"n": 2}]


def test_usage_is_summed_per_run(db: Connection) -> None:
    fda(db, "F-1", "Listeria")
    db.commit()
    result = run(db)
    assert result.usage.requests == 1
    assert result.as_log()["requests"] == 1
    assert result.as_log()["model"] == "fake"
