"""The fake model answers T6 in every language, through the same `classify` path and
checks as a real model; its flaws exercise every check."""

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.run import classify
from openfoodalerts.classify.summary import SUMMARY_TASKS, SummaryTask
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

TAXONOMY = load_taxonomy(default_taxonomy_path())
NVWA = {
    "title": "Veiligheidswaarschuwing Melkunie Protein Pudding 450g",
    "summary": "Melkunie roept Protein Pudding terug omdat er glas in kan zitten.",
    "products": "Melkunie Protein Pudding THT 07-01-2027",
}
FDA = {"product_description": "Lior Cinnamon 90g", "reason_for_recall": "Elevated lead."}


def run(task_name: str, source: str, snapshot: dict[str, str], flaw: str | None = None):  # type: ignore[no-untyped-def]
    task = SummaryTask(task_name.removeprefix("summary_"))
    fake = KeywordClassifier(TAXONOMY, summary_flaw=flaw)
    return classify(task, load_prompt(task_name), fake, source, snapshot)


@pytest.mark.parametrize("task_name", SUMMARY_TASKS)
def test_the_fake_writes_a_valid_summary_in_each_language(task_name: str) -> None:
    for source, snapshot in (("nvwa", NVWA), ("openfda", FDA)):
        if source not in SummaryTask(task_name.removeprefix("summary_")).sources:
            continue
        result = run(task_name, source, snapshot)
        assert not result.verdict.abstained, result.verdict.abstain_reason
        value = result.verdict.value
        assert value["locale"] == task_name.removeprefix("summary_")
        assert "fake" in value["summary"].casefold() or "假模型" in value["summary"]
        assert (result.model, result.prompt_version, result.taxonomy_version) == (
            "fake",
            "v1",
            None,
        )


def test_the_fake_abstains_when_the_input_is_empty() -> None:
    result = run("summary_nl", "nvwa", {"title": "", "summary": "", "products": ""})
    assert result.verdict.abstain_reason == "model_abstained"


@pytest.mark.parametrize(
    ("flaw", "reason"),
    [
        ("too_long", "too_long"),
        ("new_number", "number_not_in_input"),
        ("link", "contains_link"),
        ("wrong_language", "wrong_language"),
        ("severity", "severity_not_in_input"),
        ("not_json", "invalid_output"),
    ],
)
@pytest.mark.parametrize("task_name", SUMMARY_TASKS)
def test_the_fakes_flaws_are_caught_by_the_checks(task_name: str, flaw: str, reason: str) -> None:
    result = run(task_name, "nvwa", NVWA, flaw)
    assert result.verdict.abstain_reason == reason
