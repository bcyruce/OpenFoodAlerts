"""A reviewer's correction is checked by the task like a model output (ticket 20)."""

from collections.abc import Mapping
from typing import Any

import pytest

from openfoodalerts.classify.evidence import find_evidence
from openfoodalerts.classify.review import (
    REVIEWER_ABSTAINED,
    ReviewError,
    check_correction,
    choices,
    value_fields,
)
from openfoodalerts.classify.tasks import (
    EVIDENCE_NOT_IN_INPUT,
    HazardCategoryTask,
    Verdict,
    abstain,
)
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

T1 = HazardCategoryTask(load_taxonomy(default_taxonomy_path()))
SNAPSHOT = {"product_description": "Cookies", "reason_for_recall": "Undeclared  milk"}


class HazardTask(HazardCategoryTask):
    """Shaped like T3 (ticket 17): a free-text value that must be verbatim in the input."""

    name = "hazard"

    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "evidence_span": {"type": "string"},
                "hazard": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
        }

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if not isinstance(output, Mapping):
            return abstain(failure or "invalid_output", output)
        hazard = output.get("hazard")
        if not isinstance(hazard, str) or find_evidence(hazard, snapshot) is None:
            return abstain(EVIDENCE_NOT_IN_INPUT, dict(output))
        return Verdict(hazard, "high", False, hazard, None, {"hazard": hazard})


def test_the_value_fields_and_choices_come_from_the_output_schema() -> None:
    assert list(value_fields(T1)) == ["category"]
    t1_choices = choices(T1, "category")
    assert t1_choices is not None
    assert t1_choices == T1.taxonomy.labels
    assert "abstain" not in t1_choices
    assert list(value_fields(HazardTask(T1.taxonomy))) == ["hazard"]
    assert choices(HazardTask(T1.taxonomy), "hazard") is None


def test_a_label_of_the_taxonomy_is_accepted() -> None:
    assert check_correction(T1, {"category": "allergens"}, SNAPSHOT) == {"category": "allergens"}


def test_a_label_outside_the_taxonomy_is_refused() -> None:
    with pytest.raises(ReviewError, match="invalid_output"):
        check_correction(T1, {"category": "Allergens"}, SNAPSHOT)


def test_abstain_or_none_is_a_reviewer_abstain() -> None:
    for value in (None, {"category": "abstain"}):
        stored = check_correction(T1, value, SNAPSHOT)
        assert stored["category"] is None
        assert stored["abstain_reason"] == REVIEWER_ABSTAINED


def test_a_free_text_value_must_be_verbatim_when_the_task_says_so() -> None:
    task = HazardTask(T1.taxonomy)
    assert check_correction(task, {"hazard": "Undeclared milk"}, SNAPSHOT) == {
        "hazard": "Undeclared milk"
    }
    with pytest.raises(ReviewError, match="evidence_not_in_input"):
        check_correction(task, {"hazard": "milk allergen"}, SNAPSHOT)


def test_a_notification_without_text_cannot_be_corrected() -> None:
    with pytest.raises(ReviewError, match="no text"):
        check_correction(T1, {"category": "allergens"}, {"product_description": "  "})
