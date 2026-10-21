"""The effective value of an AI classification: the reviewer's value over the model's."""

from typing import Any

from openfoodalerts.classify.effective import effective_value

ABSTAIN: dict[str, Any] = {
    "category": None,
    "abstain_reason": "model_abstained",
    "model_output": {},
}


def row(value: dict[str, Any], **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "value": value,
        "abstained": value.get("abstain_reason") is not None,
        "review_status": "unreviewed",
        "reviewed_value": None,
    }
    return out | kw


def test_an_unreviewed_answer_is_the_model_value() -> None:
    assert effective_value(row({"category": "allergens"})) == {"category": "allergens"}


def test_an_unreviewed_abstain_has_no_value() -> None:
    assert effective_value(row(ABSTAIN)) is None


def test_a_correction_replaces_the_model_value() -> None:
    corrected = row(
        {"category": "allergens"},
        review_status="corrected",
        reviewed_value={"category": "food additives"},
    )
    assert effective_value(corrected) == {"category": "food additives"}


def test_a_correction_gives_an_abstained_row_a_value() -> None:
    corrected = row(ABSTAIN, review_status="corrected", reviewed_value={"category": "allergens"})
    assert effective_value(corrected) == {"category": "allergens"}


def test_a_reviewer_abstain_removes_the_model_value() -> None:
    corrected = row(
        {"category": "allergens"},
        review_status="corrected",
        reviewed_value={"category": None, "abstain_reason": "reviewer_abstained"},
    )
    assert effective_value(corrected) is None


def test_an_approved_row_keeps_its_value_or_its_abstain() -> None:
    answer = {"category": "allergens"}
    assert effective_value(row(answer, review_status="approved", reviewed_value=answer)) == answer
    assert effective_value(row(ABSTAIN, review_status="approved", reviewed_value=ABSTAIN)) is None
