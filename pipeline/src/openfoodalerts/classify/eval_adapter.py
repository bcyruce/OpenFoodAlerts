"""The classifiers of `make eval-refresh` (plug-in point `eval.refresh.CLASSIFIERS`).

Each registered model classifies the split's eval items with the current prompt of every
task it supports (T1-T5), on the Sources the task is scored on (T1 also RASFF subjects,
T2-T5 NVWA and openFDA), and returns the cache
lines (`ModelOutput`) for `eval.cache.write_outputs`. Inputs are the frozen snapshots of
items.csv, so the outputs and `input_hash` match what `ofa classify` stores for the same
text. Identical inputs are sent once. Every call is made again on each refresh (that is
what refresh means; cost per run: see docs/implementation-log.md ### 16). Token usage is
logged as one `eval_refresh_usage` JSON line on stderr.
"""

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime

from openfoodalerts.classify.model import Classifier, Usage
from openfoodalerts.classify.prompts import Prompt, load_prompt
from openfoodalerts.classify.registry import MODELS, make_classifier
from openfoodalerts.classify.run import Classification, classify, hash_for
from openfoodalerts.classify.summary import summary_tasks
from openfoodalerts.classify.tasks import HazardCategoryTask, Task
from openfoodalerts.classify.tasks_t2_t5 import t2_t5_tasks
from openfoodalerts.eval.cache import ModelOutput
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.jobs import log_event


def to_output(item_id: str, result: Classification, created_at: str) -> ModelOutput:
    v = result.verdict
    return ModelOutput(
        item_id=item_id,
        task=result.task,
        value=v.category,
        confidence=v.confidence,
        abstained=v.abstained,
        evidence_span=v.evidence_span,
        input_hash=result.input_hash,
        model=result.model,
        prompt_version=result.prompt_version,
        schema_version=result.schema_version,
        taxonomy_version=result.taxonomy_version or "",
        created_at=created_at,
    )


def eval_outputs(
    items: Sequence[ItemRow],
    *,
    task: Task,
    prompt: Prompt,
    classifier: Classifier,
    created_at: str,
    usage: Usage | None = None,
) -> list[ModelOutput]:
    results: dict[str, Classification] = {}
    outputs = []
    for item in items:
        if item.source not in task.eval_sources:
            continue
        key = hash_for(task, prompt, classifier.model, item.input)
        if key not in results:
            results[key] = classify(task, prompt, classifier, item.source, item.input, usage=usage)
        outputs.append(to_output(item.item_id, results[key], created_at))
    return outputs


class RefreshClassifier:
    """The registered refresh function of one model. After a call, `usage_by_task` holds
    each task's prompt version and token usage; `eval.refresh.refresh_cache` writes it to
    eval/cache/{model}/usage.json (the cost side of `ofa eval-compare`, ticket 21)."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.usage_by_task: dict[str, tuple[str, Usage]] = {}
        self.refreshed_at = ""

    def __call__(self, items: Sequence[ItemRow]) -> Iterable[ModelOutput]:
        taxonomy = load_taxonomy(default_taxonomy_path())
        classifier = make_classifier(self.model, taxonomy)  # fails here without an API key
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.refreshed_at = created_at
        self.usage_by_task = {}
        total = Usage()
        outputs: list[ModelOutput] = []
        # T6: the summaries are cached for the human fact-check (eval.factcheck), not scored
        tasks: tuple[Task, ...] = (HazardCategoryTask(taxonomy), *t2_t5_tasks(), *summary_tasks())
        for task in tasks:
            prompt = load_prompt(task.name)
            usage = Usage()
            outputs += eval_outputs(
                items,
                task=task,
                prompt=prompt,
                classifier=classifier,
                created_at=created_at,
                usage=usage,
            )
            self.usage_by_task[task.name] = (prompt.version, usage)
            total.add(usage)
        log_event("eval_refresh_usage", model=self.model, items=len(items), **total.as_dict())
        return outputs


def refresh_classifier(model: str) -> RefreshClassifier:
    return RefreshClassifier(model)


def eval_classifiers() -> dict[str, Callable[[Sequence[ItemRow]], Iterable[ModelOutput]]]:
    return {model: refresh_classifier(model) for model in MODELS}
