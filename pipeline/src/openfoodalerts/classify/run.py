"""One AI classification: prompt + task + Classifier -> a validated, versioned result.

Used by both `ofa classify` (rows in ai_classifications) and `make eval-refresh` (lines in
eval/cache/), so production and eval outputs come from the same code path.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.classify.model import Classifier, ModelRequest, ModelResponse, Usage
from openfoodalerts.classify.prompts import Prompt
from openfoodalerts.classify.tasks import Task, Verdict


@dataclass(frozen=True)
class Classification:
    task: str
    verdict: Verdict
    model: str
    prompt_version: str
    schema_version: str
    taxonomy_version: str | None
    input_hash: str


def hash_for(task: Task, prompt: Prompt, model: str, snapshot: Mapping[str, str]) -> str:
    return input_hash(
        snapshot,
        prompt_version=prompt.version,
        model=model,
        taxonomy_version=task.taxonomy_version or "",
    )


def make_request(
    task: Task, prompt: Prompt, source: str, snapshot: Mapping[str, str]
) -> ModelRequest:
    return ModelRequest(
        task=task.name,
        source=source,
        snapshot=snapshot,
        system=prompt.system,
        user=task.render_input(source, snapshot),
        output_schema=task.output_schema(),
    )


def classify(
    task: Task,
    prompt: Prompt,
    classifier: Classifier,
    source: str,
    snapshot: Mapping[str, str],
    *,
    usage: Usage | None = None,
) -> Classification:
    """Call the model once and validate its output. Raises ItemFailed / ClassifierUnavailable
    from the Classifier; every other problem is an abstain with a reason."""
    if task.name != prompt.task:
        raise ValueError(f"prompt {prompt.task}/{prompt.version} is not for task {task.name}")
    response = classifier.complete(make_request(task, prompt, source, snapshot))
    if usage is not None:
        usage.add(response.usage)
        usage.requests += 1
    return checked(task, prompt, classifier.model, snapshot, response)


def checked(
    task: Task,
    prompt: Prompt,
    model: str,
    snapshot: Mapping[str, str],
    response: ModelResponse,
) -> Classification:
    """A model response validated by the task (`Task.check`) and versioned: the same for a
    synchronous call and a Batch result."""
    return Classification(
        task=task.name,
        verdict=task.check(response.output, snapshot, failure=response.failure),
        model=model,
        prompt_version=prompt.version,
        schema_version=task.schema_version,
        taxonomy_version=task.taxonomy_version,
        input_hash=hash_for(task, prompt, model, snapshot),
    )
