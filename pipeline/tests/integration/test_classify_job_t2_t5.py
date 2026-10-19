"""`ofa classify` for T2-T5 with the fake model: T5's scope and Product type writes, the
order T5 -> T1-T4, derived rows for copied results."""

from datetime import UTC, datetime

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.job import ClassifyRun, classify_notifications
from openfoodalerts.classify.model import ModelRequest, ModelResponse
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.tasks import RUN_ORDER, make_task
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
TAXONOMY = load_taxonomy(default_taxonomy_path())


class Counting:
    def __init__(self) -> None:
        self.model = "fake"
        self.calls: list[str] = []
        self.fake = KeywordClassifier(TAXONOMY)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.task)
        return self.fake.complete(request)


def run(db: Connection, name: str, model: Counting | None = None, **kw: object) -> ClassifyRun:
    classifier = model or Counting()
    return classify_notifications(
        db,
        task=make_task(name, TAXONOMY),
        prompt=load_prompt(name),
        model="fake",
        make_classifier=lambda: classifier,
        **kw,  # type: ignore[arg-type]
    )


def nvwa(db: Connection, key: str, title: str, summary: str, **kw: object) -> int:
    return add_notification(
        db,
        "nvwa",
        key,
        first_seen_at=T,
        title=title,
        summary_source=summary,
        **kw,  # type: ignore[arg-type]
    )


def product_type(db: Connection, nid: int) -> tuple[str | None, str]:
    row = db.execute(
        "SELECT product_type, product_type_provenance FROM notifications WHERE id = %s", (nid,)
    ).fetchone()
    assert row is not None
    return row["product_type"], row["product_type_provenance"]


def test_the_run_order_is_t5_first() -> None:
    assert RUN_ORDER[:5] == (
        "product_type",
        "hazard_category",
        "product_category",
        "hazard",
        "origin_country",
    )


def test_t5_classifies_only_what_the_rules_left_pending(db: Connection) -> None:
    mill = nvwa(
        db, "/a", "Veiligheidswaarschuwing pepermolen", "Er komt lood vrij.", product_type=None
    )
    toy = nvwa(
        db, "/b", "Veiligheidswaarschuwing speelgoed", "Gebruik het niet.", product_type=None
    )
    vague = nvwa(db, "/c", "Veiligheidswaarschuwing Zeeman", "Breng het terug.", product_type=None)
    ruled = nvwa(db, "/d", "Veiligheidswaarschuwing kaas", "Listeria.")
    db.commit()
    result = run(db, "product_type")
    assert (result.candidates, result.classified, result.abstained, result.written) == (3, 3, 1, 3)
    assert product_type(db, mill) == ("food contact material", "ai")
    assert product_type(db, toy) == ("non-food", "ai")
    # an abstain counts as food: shown, in the Digest, and an Instant email trigger for NVWA
    assert product_type(db, vague) == ("food", "ai")
    assert product_type(db, ruled) == ("food", "official")
    # T5's own results stay in scope (a changed text is classified again); nothing new here
    again = run(db, "product_type")
    assert (again.candidates, again.done, again.classified) == (3, 3, 0)


def test_non_food_gets_no_other_task_and_t5s_food_does(db: Connection) -> None:
    toy = nvwa(db, "/b", "Veiligheidswaarschuwing speelgoed", "Bevat lood.", product_type=None)
    vague = nvwa(db, "/c", "Veiligheidswaarschuwing Zeeman", "Bevat Listeria.", product_type=None)
    db.commit()
    model = Counting()
    for name in RUN_ORDER:
        run(db, name, model)
    assert model.calls.count("product_type") == 2
    for name in ("hazard_category", "product_category", "hazard", "origin_country"):
        assert model.calls.count(name) == 1, name
    tasks = db.execute(
        "SELECT notification_id, array_agg(task ORDER BY task) AS tasks FROM ai_classifications"
        " GROUP BY 1"
    ).fetchall()
    assert {r["notification_id"]: r["tasks"] for r in tasks} == {
        toy: ["product_type"],
        vague: ["hazard", "hazard_category", "origin_country", "product_category", "product_type"],
    }
    [hazard] = db.execute(
        "SELECT hazard_name FROM notification_hazards WHERE hazard_name IS NOT NULL"
    ).fetchall()
    assert hazard == {"hazard_name": "Listeria"}


def fda(db: Connection, key: str, product: str, reason: str) -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason)
    db.execute("UPDATE notifications SET product_text = %s WHERE id = %s", (product, nid))
    return nid


def test_t2_and_t4_write_their_rows_also_for_copied_results(db: Connection) -> None:
    a = fda(db, "F-1", "Pecorino cheese. Product of Italy.", "Listeria")
    b = fda(db, "F-2", "Pecorino cheese. Product of Italy.", "Listeria")
    db.commit()
    model = Counting()
    t2 = run(db, "product_category", model)
    t4 = run(db, "origin_country", model)
    assert (t2.classified, t2.reused, t2.written) == (1, 1, 2)
    assert (t4.classified, t4.reused, t4.written) == (1, 1, 2)
    assert model.calls == ["product_category", "origin_country"]
    categories = db.execute(
        "SELECT p.notification_id, c.name_en FROM notification_product_categories p"
        " JOIN product_categories c ON c.id = p.product_category_id ORDER BY 1"
    ).fetchall()
    assert [(r["notification_id"], r["name_en"]) for r in categories] == [
        (a, "milk and milk products"),
        (b, "milk and milk products"),
    ]
    countries = db.execute(
        "SELECT notification_id, country_iso2 FROM notification_countries"
        " WHERE role = 'origin' AND provenance = 'ai' ORDER BY 1"
    ).fetchall()
    assert [(r["notification_id"], r["country_iso2"]) for r in countries] == [(a, "IT"), (b, "IT")]
    copied = db.execute(
        "SELECT value FROM ai_classifications WHERE task = 'origin_country' ORDER BY id"
    ).fetchall()
    assert [r["value"] for r in copied] == [{"country": "IT"}, {"country": "IT"}]
