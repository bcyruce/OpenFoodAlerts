"""T2-T5: output schemas and the code-side validation (spec §6.1, ADR 0006)."""

import pytest

from openfoodalerts.classify.tasks import make_task
from openfoodalerts.classify.tasks_t2_t5 import (
    HazardTask,
    OriginCountryTask,
    ProductCategoryTask,
    ProductTypeTask,
)
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

FDA = {
    "product_description": "Organic Cashew Pieces, 8 oz bag. Product of Vietnam.",
    "reason_for_recall": "Potential  contamination\nwith Salmonella.",
}
NVWA = {
    "title": "Veiligheidswaarschuwing pindakaas",
    "summary": "De pindakaas komt uit Nederland en bevat mogelijk glas.",
    "products": "Pindakaas 350 gram",
}


def test_t2_accepts_a_rasff_product_category_with_a_verbatim_span() -> None:
    task = ProductCategoryTask()
    out = {
        "evidence_span": "Organic Cashew Pieces",
        "category": "nuts, nut products and seeds",
        "confidence": "high",
    }
    verdict = task.check(out, FDA)
    assert not verdict.abstained
    assert verdict.category == "nuts, nut products and seeds"
    assert verdict.value == {"category": "nuts, nut products and seeds"}
    assert verdict.evidence_span == "Organic Cashew Pieces"


def test_t2_schema_is_the_37_rasff_product_categories_plus_abstain() -> None:
    schema = ProductCategoryTask().output_schema()
    assert schema["required"] == ["evidence_span", "category", "confidence"]
    assert schema["additionalProperties"] is False
    enum = schema["properties"]["category"]["enum"]
    assert len(enum) == 38 and enum[-1] == "abstain"
    assert "herbs and spices" in enum and "pet food" in enum and "food contact materials" in enum


@pytest.mark.parametrize(
    ("out", "reason"),
    [
        ({"evidence_span": "", "category": "abstain", "confidence": "low"}, "model_abstained"),
        ({"evidence_span": "Cashew", "category": "nuts", "confidence": "high"}, "invalid_output"),
        (
            {
                "evidence_span": "cashew pieces",
                "category": "nuts, nut products and seeds",
                "confidence": "high",
            },
            "evidence_not_in_input",
        ),
        ({"category": "fruits and vegetables", "confidence": "high"}, "invalid_output"),
        ("not json", "invalid_output"),
    ],
)
def test_t2_anything_else_is_an_abstain_with_a_reason(out: object, reason: str) -> None:
    verdict = ProductCategoryTask().check(out, FDA)
    assert verdict.abstained and verdict.category is None
    assert verdict.value["category"] is None
    assert verdict.value["abstain_reason"] == reason


def test_t5_answers_a_product_type_with_its_own_value_key() -> None:
    task = ProductTypeTask()
    assert task.output_schema()["properties"]["product_type"]["enum"] == [
        "food",
        "feed",
        "food contact material",
        "non-food",
        "abstain",
    ]
    out = {"evidence_span": "Pindakaas 350 gram", "product_type": "food", "confidence": "high"}
    verdict = task.check(out, NVWA)
    assert (verdict.category, verdict.value) == ("food", {"product_type": "food"})
    gone = task.check(None, NVWA, failure="refusal")
    assert gone.abstained and gone.value == {
        "product_type": None,
        "abstain_reason": "refusal",
        "model_output": None,
    }


# T3 -----------------------------------------------------------------------------------


def test_t3_the_hazard_is_a_verbatim_span_of_one_field_whitespace_normalized() -> None:
    task = HazardTask()
    schema = task.output_schema()
    assert schema["required"] == ["hazard", "confidence"]
    verdict = task.check({"hazard": " contamination with Salmonella", "confidence": "high"}, FDA)
    assert not verdict.abstained
    # the input's whitespace (two spaces, a newline) does not have to be copied exactly;
    # the stored Hazard is the span with whitespace collapsed
    assert verdict.value == {"hazard": "contamination with Salmonella"}
    assert verdict.category == verdict.evidence_span == "contamination with Salmonella"


@pytest.mark.parametrize(
    ("out", "reason"),
    [
        ({"hazard": "", "confidence": "low"}, "model_abstained"),
        ({"hazard": "salmonella", "confidence": "high"}, "evidence_not_in_input"),  # case
        ({"hazard": "Salmonella spp.", "confidence": "high"}, "evidence_not_in_input"),
        # joins two fields
        ({"hazard": "Vietnam. Potential", "confidence": "high"}, "evidence_not_in_input"),
        ({"hazard": "Salmonella", "confidence": "certain"}, "invalid_output"),
        ({"hazard": "x" * 151, "confidence": "high"}, "invalid_output"),
        ({"hazard": None, "confidence": "high"}, "invalid_output"),
    ],
)
def test_t3_anything_not_verbatim_is_an_abstain(out: object, reason: str) -> None:
    snapshot = FDA | {"reason_for_recall": FDA["reason_for_recall"] + " " + "x" * 151}
    verdict = HazardTask().check(out, snapshot)
    assert verdict.abstained
    assert verdict.value["hazard"] is None and verdict.value["abstain_reason"] == reason


# T4 -----------------------------------------------------------------------------------


def test_t4_a_country_needs_a_verbatim_span_that_states_it() -> None:
    task = OriginCountryTask()
    enum = task.output_schema()["properties"]["country"]["enum"]
    assert enum[0] == "unknown" and "NL" in enum and "VN" in enum and "XI" in enum
    assert "ECDC" not in enum and "abstain" not in enum
    out = {"evidence_span": "Product of Vietnam", "country": "VN", "confidence": "high"}
    verdict = task.check(out, FDA)
    assert (verdict.category, verdict.value, verdict.abstained) == ("VN", {"country": "VN"}, False)
    assert verdict.evidence_span == "Product of Vietnam"


def test_t4_unknown_is_an_answer_without_a_span_not_an_abstain() -> None:
    out = {"evidence_span": "", "country": "unknown", "confidence": "high"}
    verdict = OriginCountryTask().check(out, FDA)
    assert not verdict.abstained
    assert (verdict.category, verdict.value, verdict.evidence_span) == (
        "unknown",
        {"country": "unknown"},
        None,
    )


@pytest.mark.parametrize(
    ("out", "reason"),
    [
        ({"evidence_span": "uit Nederland", "country": "NL", "confidence": "high"}, None),
        ({"evidence_span": "", "country": "NL", "confidence": "high"}, "evidence_not_in_input"),
        (
            {"evidence_span": "from Holland", "country": "NL", "confidence": "high"},
            "evidence_not_in_input",
        ),
        (
            {"evidence_span": "uit Nederland", "country": "nl", "confidence": "high"},
            "invalid_output",
        ),
        (
            {"evidence_span": "uit Nederland", "country": "EUROPOL", "confidence": "high"},
            "invalid_output",
        ),
    ],
)
def test_t4_checks(out: object, reason: str | None) -> None:
    verdict = OriginCountryTask().check(out, NVWA)
    assert verdict.abstained == (reason is not None)
    assert verdict.abstain_reason == reason


def test_the_tasks_are_registered_by_name() -> None:
    taxonomy = load_taxonomy(default_taxonomy_path())
    for name in ("product_category", "hazard", "origin_country", "product_type"):
        task = make_task(name, taxonomy)
        assert task.name == name
        assert task.sources == ("nvwa", "openfda") == task.eval_sources
        assert task.taxonomy_version is None and task.schema_version == "1"
