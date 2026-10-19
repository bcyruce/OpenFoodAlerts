"""One classification: prompt + task -> request -> Classifier -> validated, versioned result."""

from collections.abc import Mapping

import pytest

from openfoodalerts.classify.fake import FAKE_MODEL, KeywordClassifier
from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.classify.model import ModelRequest, ModelResponse, Usage
from openfoodalerts.classify.prompts import Prompt, load_prompt
from openfoodalerts.classify.run import classify, make_request
from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

SNAPSHOT = {"product_description": "Cookies", "reason_for_recall": "Undeclared peanut."}


class Scripted:
    """A Classifier that answers with a fixed output and records its requests."""

    model = "scripted-model"

    def __init__(self, output: object, failure: str | None = None) -> None:
        self.output, self.failure = output, failure
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.output, self.failure, Usage(input_tokens=10, output_tokens=3))


@pytest.fixture(scope="module")
def task() -> HazardCategoryTask:
    return HazardCategoryTask(load_taxonomy(default_taxonomy_path()))


@pytest.fixture(scope="module")
def prompt() -> Prompt:
    return load_prompt("hazard_category", "v1")


def test_the_request_is_the_fixed_prompt_plus_the_item(
    task: HazardCategoryTask, prompt: Prompt
) -> None:
    request = make_request(task, prompt, "openfda", SNAPSHOT)
    assert request.system == prompt.system
    assert request.user == task.render_input("openfda", SNAPSHOT)
    assert request.output_schema == task.output_schema()
    assert request.snapshot == SNAPSHOT and request.source == "openfda"


def test_a_result_records_every_version_and_the_input_hash(
    task: HazardCategoryTask, prompt: Prompt
) -> None:
    model = Scripted({"evidence_span": "peanut", "category": "allergens", "confidence": "high"})
    usage = Usage()
    result = classify(task, prompt, model, "openfda", SNAPSHOT, usage=usage)
    assert result.verdict.category == "allergens"
    assert (result.task, result.model, result.prompt_version) == (
        "hazard_category",
        "scripted-model",
        "v1",
    )
    assert result.schema_version == "1"
    assert result.taxonomy_version == task.taxonomy_version
    assert result.input_hash == input_hash(
        SNAPSHOT,
        prompt_version="v1",
        model="scripted-model",
        taxonomy_version=task.taxonomy_version,
    )
    assert usage == Usage(requests=1, input_tokens=10, output_tokens=3)


def test_a_span_that_is_not_in_the_input_is_stored_as_an_abstain(
    task: HazardCategoryTask, prompt: Prompt
) -> None:
    out = {"evidence_span": "peanuts", "category": "allergens", "confidence": "high"}
    result = classify(task, prompt, Scripted(out), "openfda", SNAPSHOT)
    assert result.verdict.abstained
    assert result.verdict.abstain_reason == "evidence_not_in_input"
    refused = classify(task, prompt, Scripted(None, "refusal"), "openfda", SNAPSHOT)
    assert refused.verdict.abstain_reason == "refusal"


def test_usage_adds_up() -> None:
    total = Usage()
    total.add(Usage(1, 100, 10, 50, 0))
    total.add(Usage(1, 20, 12, 0, 50))
    assert total == Usage(2, 120, 22, 50, 50)
    assert total.as_dict() == {
        "requests": 2,
        "input_tokens": 120,
        "output_tokens": 22,
        "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 50,
    }


@pytest.mark.parametrize(
    ("source", "snapshot", "category", "confidence"),
    [
        (
            "openfda",
            {"product_description": "Brie", "reason_for_recall": "Listeria."},
            "pathogenic micro-organisms",
            "high",
        ),
        (
            "nvwa",
            {"title": "Waarschuwing", "summary": "Bevat mogelijk glasdeeltjes.", "products": ""},
            "foreign bodies",
            "high",
        ),
        (
            "openfda",
            {"product_description": "Undeclared milk", "reason_for_recall": "See label."},
            "allergens",
            "medium",
        ),
        ("rasff", {"subject": "2026.0001"}, None, None),
    ],
)
def test_the_fake_model_answers_with_the_keyword_rules_through_the_same_checks(
    task: HazardCategoryTask,
    prompt: Prompt,
    source: str,
    snapshot: Mapping[str, str],
    category: str | None,
    confidence: str | None,
) -> None:
    fake = KeywordClassifier(task.taxonomy)
    assert fake.model == FAKE_MODEL == "fake"
    result = classify(task, prompt, fake, source, snapshot)
    assert result.verdict.category == category
    assert result.verdict.confidence == confidence
    assert result.verdict.abstained is (category is None)
    if category:
        assert result.verdict.evidence_span
    else:
        assert result.verdict.abstain_reason == "model_abstained"


def test_the_fake_model_can_be_told_to_quote_badly(
    task: HazardCategoryTask, prompt: Prompt
) -> None:
    fake = KeywordClassifier(task.taxonomy, garble_spans=True)
    result = classify(task, prompt, fake, "openfda", {"reason_for_recall": "Listeria found."})
    assert result.verdict.abstain_reason == "evidence_not_in_input"
