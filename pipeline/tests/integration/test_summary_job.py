"""`ofa classify --task summary_{en,nl,zh}` against the test database, with the fake model:
scope per language, one row per (Notification, language), idempotency, input_hash dedupe."""

from datetime import UTC, datetime

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.job import ClassifyRun, classify_notifications
from openfoodalerts.classify.model import ModelRequest, ModelResponse
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.run import hash_for
from openfoodalerts.classify.summary import SUMMARY_TASKS, SummaryTask
from openfoodalerts.classify.tasks import HazardCategoryTask, Task
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
TAXONOMY = load_taxonomy(default_taxonomy_path())


class Counting:
    def __init__(self, flaw: str | None = None) -> None:
        self.model = "fake"
        self.calls = 0
        self.fake = KeywordClassifier(TAXONOMY, summary_flaw=flaw)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return self.fake.complete(request)


def run(db: Connection, task: Task, model: Counting | None = None) -> ClassifyRun:
    classifier = model or Counting()
    return classify_notifications(
        db,
        task=task,
        prompt=load_prompt(task.name),
        model="fake",
        make_classifier=lambda: classifier,
    )


def nvwa(db: Connection, key: str, **kw: object) -> int:
    return add_notification(
        db,
        "nvwa",
        key,
        first_seen_at=T,
        title=f"Veiligheidswaarschuwing Pindakaas {key}",
        summary_source="Het product bevat glas.",
        **kw,  # type: ignore[arg-type]
    )


def fda(db: Connection, key: str, reason: str = "Undeclared peanut.") -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason)
    db.execute("UPDATE notifications SET product_text = 'Cookies 12 oz' WHERE id = %s", (nid,))
    return nid


def rows(db: Connection, task: str) -> list[dict[str, object]]:
    return db.execute(
        "SELECT * FROM ai_classifications WHERE task = %s ORDER BY notification_id", (task,)
    ).fetchall()


def test_zh_summarizes_nvwa_only_en_and_nl_also_fda_never_rasff_or_non_food(
    db: Connection,
) -> None:
    food = nvwa(db, "/a")
    fcm = nvwa(db, "/b", product_type="food contact material")
    nvwa(db, "/c", product_type="non-food")
    nvwa(db, "/d", product_type=None)  # T5 pending
    add_notification(db, "rasff", "2026.1", first_seen_at=T, title="Listeria in cheese")
    recall = fda(db, "F-1")
    db.commit()
    assert run(db, SummaryTask("zh")).classified == 2
    assert [r["notification_id"] for r in rows(db, "summary_zh")] == [food, fcm]
    for locale in ("en", "nl"):
        assert run(db, SummaryTask(locale)).classified == 3
        got = [r["notification_id"] for r in rows(db, f"summary_{locale}")]
        assert got == sorted([food, fcm, recall])


def test_a_summary_row_has_its_language_and_provenance(db: Connection) -> None:
    nid = nvwa(db, "/a")
    db.commit()
    task = SummaryTask("zh")
    run(db, task)
    [row] = rows(db, "summary_zh")
    snapshot = {
        "title": "Veiligheidswaarschuwing Pindakaas /a",
        "summary": "Het product bevat glas.",
        "products": "",
    }
    assert row["notification_id"] == nid
    assert row["value"] == {
        "locale": "zh",
        "summary": "测试用假模型摘要：此处复述NVWA关于 Pindakaas /a 的通报，不添加新的事实。",
    }
    assert (row["confidence"], row["abstained"], row["evidence_span"]) == ("medium", False, None)
    assert (row["model"], row["prompt_version"], row["schema_version"]) == ("fake", "v1", "1")
    assert row["taxonomy_version"] is None
    assert row["input_hash"] == hash_for(task, load_prompt("summary_zh"), "fake", snapshot)


def test_every_language_is_its_own_row_and_a_second_run_calls_nothing(db: Connection) -> None:
    nvwa(db, "/a")
    db.commit()
    model = Counting()
    for name in SUMMARY_TASKS:
        run(db, SummaryTask(name.removeprefix("summary_")), model)
    assert model.calls == 3
    again = [run(db, SummaryTask(n.removeprefix("summary_")), model) for n in SUMMARY_TASKS]
    assert model.calls == 3 and all(r.done == 1 and r.classified == 0 for r in again)
    count = db.execute("SELECT count(*) AS n FROM ai_classifications").fetchone()
    assert count is not None and count["n"] == 3


def test_identical_inputs_are_summarized_once(db: Connection) -> None:
    first, second = fda(db, "F-1"), fda(db, "F-2")
    db.commit()
    model = Counting()
    result = run(db, SummaryTask("en"), model)
    assert (model.calls, result.classified, result.reused) == (1, 1, 1)
    got = rows(db, "summary_en")
    assert [r["notification_id"] for r in got] == [first, second]
    assert got[0]["value"] == got[1]["value"]


def test_a_failed_check_is_stored_as_an_abstain_for_review(db: Connection) -> None:
    nvwa(db, "/a")
    db.commit()
    result = run(db, SummaryTask("en"), Counting(flaw="too_long"))
    assert result.abstained == 1
    [row] = rows(db, "summary_en")
    assert row["abstained"] and row["confidence"] is None
    assert row["value"]["abstain_reason"] == "too_long"  # type: ignore[index]
    assert row["value"]["summary"] is None  # type: ignore[index]


def test_summaries_leave_the_ai_hazards_of_t1_alone(db: Connection) -> None:
    fda(db, "F-1")
    db.commit()
    run(db, HazardCategoryTask(TAXONOMY))
    run(db, SummaryTask("en"))
    hazards = db.execute("SELECT count(*) AS n FROM notification_hazards").fetchone()
    assert hazards is not None and hazards["n"] == 1
