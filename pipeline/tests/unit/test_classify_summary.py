"""T6 summaries (spec §6.1): the task's output contract and its code-side checks."""

import json

import pytest

from openfoodalerts.classify.summary import SUMMARY_TASKS, SummaryTask, word_count
from openfoodalerts.classify.tasks import Verdict, make_task
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy


def test_en_and_nl_count_whitespace_words_and_ignore_bare_punctuation() -> None:
    assert word_count("Jumbo recalls peanut butter - undeclared sesame.", "en") == 6
    assert word_count("  Eet het\nproduct niet.  ", "nl") == 4


def test_zh_counts_two_characters_as_a_word_and_latin_tokens_as_words() -> None:
    # 9 Chinese characters = 5 words (rounded up); "Albert", "Heijn", "350g" = 3 words
    assert word_count("Albert Heijn 召回350g花生酱，含有玻璃。", "zh") == 3 + 5
    # an odd number of characters rounds up
    assert word_count("召回花生酱", "zh") == 3


NVWA = {
    "title": "Veiligheidswaarschuwing Melkunie Protein Pudding",
    "summary": "Melkunie roept een partij Melkunie Protein Pudding in de smaken chocolade en"
    " crème brûlée terug omdat ze mogelijk kleine glasdeeltjes bevatten. Eet het product niet.",
    "products": "Melkunie Protein Pudding Chocolate THT-data: 07-01-2027, 09-01-2027 en"
    " 06-02-2027\nDe partij is verkocht bij: AH, Boon, Jumbo, Picnic, Plus, Spar en Versunie.",
}
FDA = {
    "product_description": "Lior brand Cinnamon Ground Seasoning; 90g transparent plastic"
    " container; UPC 794711005484.",
    "reason_for_recall": "Product contains elevated levels of lead.",
}


def answer(summary: str, confidence: str = "high", abstain: bool = False) -> dict[str, object]:
    return {"abstain": abstain, "summary": summary, "confidence": confidence}


def test_a_valid_summary_is_stored_whitespace_collapsed_with_its_language() -> None:
    task = SummaryTask("en")
    verdict = task.check(
        answer(
            "Lior brand Cinnamon Ground Seasoning (UPC 794711005484) is recalled\n because"
            " it contains elevated levels of lead.  "
        ),
        FDA,
    )
    text = (
        "Lior brand Cinnamon Ground Seasoning (UPC 794711005484) is recalled because it"
        " contains elevated levels of lead."
    )
    assert verdict == Verdict(
        category=text,
        confidence="high",
        abstained=False,
        evidence_span=None,
        abstain_reason=None,
        value={"locale": "en", "summary": text},
    )
    assert task.name == "summary_en"


FORTY_ONE = " ".join(["product"] * 41)


@pytest.mark.parametrize(
    ("locale", "output", "reason"),
    [
        ("en", answer("", "low", abstain=True), "model_abstained"),
        ("en", answer("Something.", "low", abstain=True), "model_abstained"),
        ("en", {"summary": "No confidence."}, "invalid_output"),
        ("en", answer("Bad confidence.", "certain"), "invalid_output"),
        ("en", {"abstain": "no", "summary": "x", "confidence": "high"}, "invalid_output"),
        ("en", "Not JSON", "invalid_output"),
        ("en", answer("   "), "invalid_output"),
        ("en", answer(FORTY_ONE), "too_long"),
        # 82 Chinese characters = 41 words
        ("zh", answer("产品" * 41), "too_long"),
    ],
)
def test_outputs_that_fail_a_check_are_abstains_with_the_reason(
    locale: str, output: object, reason: str
) -> None:
    snapshot = FDA if locale != "zh" else NVWA
    verdict = SummaryTask(locale).check(output, snapshot)
    assert verdict.abstained and verdict.abstain_reason == reason
    assert (verdict.category, verdict.confidence, verdict.evidence_span) == (None, None, None)
    assert verdict.value == {
        "locale": locale,
        "summary": None,
        "abstain_reason": reason,
        "model_output": output,
    }


@pytest.mark.parametrize(
    ("locale", "snapshot", "summary", "ok"),
    [
        # every number is one of the source's numbers (EAN/UPC, dates, weights)
        ("en", FDA, "Lior Cinnamon (90g, UPC 794711005484) contains elevated lead.", True),
        ("nl", NVWA, "Melkunie Protein Pudding met THT 07-01-2027 kan glas bevatten.", True),
        # the same number written differently: leading zeros, date order, decimal point
        (
            "en",
            NVWA,
            "Melkunie Protein Pudding, best before 7 January 2027, may contain glass.",
            True,
        ),
        (
            "zh",
            NVWA,
            "Melkunie Protein Pudding（保质期２０２７年１月７日）可能含有玻璃碎片。",
            True,
        ),
        # a number the source does not have
        ("en", FDA, "Lior Cinnamon contains 20 times the allowed level of lead.", False),
        ("en", FDA, "Lior Cinnamon was recalled in 2026 because of lead.", False),
        ("zh", NVWA, "Melkunie Protein Pudding 共3种口味可能含有玻璃碎片。", False),
    ],
)
def test_numbers_in_a_summary_must_be_numbers_of_the_source(
    locale: str, snapshot: dict[str, str], summary: str, ok: bool
) -> None:
    verdict = SummaryTask(locale).check(answer(summary), snapshot)
    assert verdict.abstained is not ok
    if not ok:
        assert verdict.abstain_reason == "number_not_in_input"


@pytest.mark.parametrize(
    "summary",
    [
        "Lior Cinnamon contains lead; see https://www.fda.gov/safety/recalls.",
        "Lior Cinnamon contains lead; details on www.fda.gov.",
        "Lior Cinnamon contains lead; more at fda.gov or nvwa.nl.",
        "Lior Cinnamon contains lead; questions to recalls@lior.com.",
    ],
)
def test_a_summary_has_no_links_or_email_addresses(summary: str) -> None:
    verdict = SummaryTask("en").check(answer(summary), FDA)
    assert verdict.abstain_reason == "contains_link"


def test_a_brand_name_that_is_a_domain_in_the_source_is_not_a_link() -> None:
    fda = {"product_description": "Nuts.com Espresso Beans", "reason_for_recall": "Milk."}
    task = SummaryTask("en")
    assert not task.check(answer("Nuts.com Espresso Beans contain undeclared milk."), fda).abstained
    verdict = task.check(answer("Nuts.com Espresso Beans: see https://nuts.com."), fda)
    assert verdict.abstain_reason == "contains_link"


def test_abbreviations_are_not_links() -> None:
    nvwa = NVWA | {"summary": "De E. coli-bacterie (STEC) kan aanwezig zijn. Eet het niet."}
    assert not SummaryTask("en").check(answer("E. coli may be present (STEC)."), nvwa).abstained


@pytest.mark.parametrize(
    ("locale", "summary", "reason"),
    [
        # Chinese sentences, Dutch names kept verbatim
        ("zh", "Melkunie 召回 Melkunie Protein Pudding Chocolate，可能含有小玻璃碎片。", None),
        ("zh", "Melkunie roept Protein Pudding terug wegens glas.", "wrong_language"),
        ("zh", "Melkunie roept Protein Pudding terug wegens glas，请勿食用。", "wrong_language"),
        (
            "zh",
            "Melkunie 召回 Protein Pudding，產品可能含有玻璃碎片，請勿食用。",
            "traditional_chinese",
        ),
        ("en", "Melkunie recalls Protein Pudding because it may contain glass.", None),
        ("en", "Melkunie 召回 Protein Pudding because it may contain glass.", "wrong_language"),
        (
            "en",
            "Melkunie roept de Protein Pudding terug omdat het glas kan bevatten.",
            "wrong_language",
        ),
        ("nl", "Melkunie roept de Protein Pudding terug omdat het glas kan bevatten.", None),
        (
            "nl",
            "Melkunie recalls the Protein Pudding because it may contain glass.",
            "wrong_language",
        ),
        # an English product name in a Dutch summary
        (
            "nl",
            "Lior brand Cinnamon Ground Seasoning wordt teruggeroepen vanwege te veel lood.",
            None,
        ),
    ],
)
def test_the_summary_is_in_its_language(locale: str, summary: str, reason: str | None) -> None:
    verdict = SummaryTask(locale).check(answer(summary), NVWA)
    assert verdict.abstain_reason == reason


DANGER = NVWA | {
    "summary": "Het product bevat pinda. Dit kan gevaarlijk zijn voor mensen met een allergie."
}


@pytest.mark.parametrize(
    ("locale", "snapshot", "summary", "ok"),
    [
        # a severity grade or judgement the source does not make (ADR 0006)
        ("en", FDA, "Class I recall: Lior Cinnamon contains elevated lead.", False),
        ("en", FDA, "Lior Cinnamon contains lead, a serious health risk.", False),
        ("en", FDA, "Lior Cinnamon contains a dangerous level of lead.", False),
        ("nl", FDA, "Lior Cinnamon bevat te veel lood; dit is een ernstig risico.", False),
        ("zh", NVWA, "Melkunie Protein Pudding 可能含有玻璃，存在严重风险。", False),
        ("zh", NVWA, "Melkunie Protein Pudding 属于一级召回，可能含有玻璃。", False),
        # ... unless the source says so (in any of the three languages)
        ("nl", DANGER, "Het product bevat pinda en kan gevaarlijk zijn bij een allergie.", True),
        (
            "en",
            DANGER,
            "The product contains peanut and can be dangerous for people with an allergy.",
            True,
        ),
        ("zh", DANGER, "该产品含有花生，对过敏人士可能有危险。", True),
    ],
)
def test_a_summary_does_not_grade_severity(
    locale: str, snapshot: dict[str, str], summary: str, ok: bool
) -> None:
    verdict = SummaryTask(locale).check(answer(summary), snapshot)
    assert verdict.abstain_reason == (None if ok else "severity_not_in_input")


def test_languages_and_sources_follow_the_spec_and_never_include_rasff() -> None:
    taxonomy = load_taxonomy(default_taxonomy_path())
    tasks = {name: make_task(name, taxonomy) for name in SUMMARY_TASKS}
    assert {name: t.sources for name, t in tasks.items()} == {
        "summary_en": ("nvwa", "openfda"),
        "summary_nl": ("nvwa", "openfda"),
        "summary_zh": ("nvwa",),
    }
    assert all(t.eval_sources == t.sources for t in tasks.values())
    assert all(t.taxonomy_version is None for t in tasks.values())
    with pytest.raises(ValueError):
        SummaryTask("de")


def test_the_output_schema_has_no_unsupported_keywords() -> None:
    schema = SummaryTask("zh").output_schema()
    assert schema["required"] == ["abstain", "summary", "confidence"]
    assert schema["additionalProperties"] is False
    # structured outputs do not take string length limits: the code checks the length
    assert "maxLength" not in json.dumps(schema)


def test_forty_words_is_still_a_summary() -> None:
    assert not SummaryTask("en").check(answer(" ".join(["product"] * 40)), FDA).abstained
    assert not SummaryTask("zh").check(answer("产品" * 40), NVWA).abstained


def test_a_request_failure_is_an_abstain_with_that_reason() -> None:
    verdict = SummaryTask("nl").check(None, FDA, failure="refusal")
    assert verdict.abstained and verdict.abstain_reason == "refusal"
