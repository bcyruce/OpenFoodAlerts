"""The T1 task: model input, output schema and the code-side validation (ADR 0006)."""

import json

import pytest

from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

SNAPSHOT = {
    "product_description": "Cookies, 12 oz",
    "reason_for_recall": "Undeclared  peanut\nin the product.",
}


@pytest.fixture(scope="module")
def task() -> HazardCategoryTask:
    return HazardCategoryTask(load_taxonomy(default_taxonomy_path()))


def test_t1_runs_on_nvwa_and_openfda_and_is_scored_on_all_three_sources(
    task: HazardCategoryTask,
) -> None:
    assert task.name == "hazard_category"
    assert task.sources == ("nvwa", "openfda")
    assert task.eval_sources == ("rasff", "nvwa", "openfda")
    assert task.taxonomy_version == load_taxonomy(default_taxonomy_path()).version


def test_the_input_is_the_eval_snapshot_and_the_message_is_nfc_json(
    task: HazardCategoryTask,
) -> None:
    row = {"title": "Waarschuwing", "summary_source": "Bevat melk.", "product_text": None}
    assert task.build_input("nvwa", row) == {
        "title": "Waarschuwing",
        "summary": "Bevat melk.",
        "products": "",
    }
    decomposed = {"subject": "Crème"}  # "è" as e + combining grave
    message = task.render_input("rasff", decomposed)
    assert json.loads(message) == {"source": "rasff", "input": {"subject": "Crème"}}
    assert "\\u" not in message


def test_the_schema_is_an_enum_of_the_labels_plus_abstain(task: HazardCategoryTask) -> None:
    schema = task.output_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["evidence_span", "category", "confidence"]
    categories = schema["properties"]["category"]["enum"]
    assert categories[-1] == "abstain"
    assert tuple(categories[:-1]) == load_taxonomy(default_taxonomy_path()).labels
    assert schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]


def test_a_category_with_a_verbatim_span_is_accepted(task: HazardCategoryTask) -> None:
    # whitespace differences are normalized; the span keeps the model's text
    out = {"evidence_span": "Undeclared peanut in", "category": "allergens", "confidence": "high"}
    verdict = task.check(out, SNAPSHOT)
    assert not verdict.abstained
    assert verdict.category == "allergens"
    assert verdict.confidence == "high"
    assert verdict.evidence_span == "Undeclared peanut in"
    assert verdict.value == {"category": "allergens"}


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        # not in the input: paraphrased, translated, other case, joined across fields
        ({"evidence_span": "undeclared peanuts"}, "evidence_not_in_input"),
        ({"evidence_span": "UNDECLARED PEANUT"}, "evidence_not_in_input"),
        ({"evidence_span": "12 oz Undeclared"}, "evidence_not_in_input"),
        ({"evidence_span": "  "}, "evidence_not_in_input"),
        ({"evidence_span": "in"}, "evidence_not_in_input"),
        ({"category": "abstain", "evidence_span": ""}, "model_abstained"),
        ({"category": "peanuts"}, "invalid_output"),
        ({"confidence": "certain"}, "invalid_output"),
        ({"evidence_span": None}, "invalid_output"),
    ],
)
def test_anything_else_is_an_abstain_with_a_reason(
    task: HazardCategoryTask, output: dict[str, object], reason: str
) -> None:
    out: dict[str, object] = {
        "evidence_span": "Undeclared  peanut",
        "category": "allergens",
        "confidence": "high",
    }
    out |= output
    verdict = task.check(out, SNAPSHOT)
    assert verdict.abstained
    assert verdict.category is None and verdict.confidence is None
    assert verdict.evidence_span is None
    assert verdict.abstain_reason == reason
    assert verdict.value == {"category": None, "abstain_reason": reason, "model_output": out}


def test_no_output_at_all_abstains_with_the_callers_reason(task: HazardCategoryTask) -> None:
    verdict = task.check(None, SNAPSHOT, failure="refusal")
    assert verdict.abstained and verdict.abstain_reason == "refusal"
    assert verdict.value == {"category": None, "abstain_reason": "refusal", "model_output": None}
    assert task.check("not an object", SNAPSHOT).abstain_reason == "invalid_output"
