"""`make eval-refresh SPLIT=dev`: call the configured classifiers and refresh eval/cache/.

This is the only eval step that may call a paid API. A classifier is registered under its
model name in CLASSIFIERS: a function that takes the eval items of the split and yields one
`ModelOutput` per item and task, with `input_hash` from `openfoodalerts.classify.input_hash`.
Ticket 16 registers every model of `openfoodalerts.classify.registry` (Claude Haiku 5.5 and
the keyword-based `fake`) through `openfoodalerts.classify.eval_adapter`; a model that
cannot run (no API key) raises `ClassifierUnavailable` before any call. With an empty
registry, refresh fails with "no classifier configured".
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from openfoodalerts.classify.eval_adapter import eval_classifiers
from openfoodalerts.eval.cache import ModelOutput, write_outputs, write_usage
from openfoodalerts.eval.files import ItemRow

Classifier = Callable[[Sequence[ItemRow]], Iterable[ModelOutput]]

CLASSIFIERS: dict[str, Classifier] = eval_classifiers()


class NoClassifierConfigured(RuntimeError):
    pass


def refresh_cache(
    items: Sequence[ItemRow],
    *,
    split: str,
    cache_dir: Path,
    classifiers: Mapping[str, Classifier] | None = None,
    models: Sequence[str] | None = None,
) -> dict[Path, int]:
    """Run the classifiers on the split's items; returns outputs written per cache file."""
    registry = CLASSIFIERS if classifiers is None else classifiers
    if not registry:
        raise NoClassifierConfigured(
            "no classifier configured: eval-refresh needs a registered classifier; "
            "`make eval` scores the existing cache and the baselines"
        )
    for name in models or ():
        if name not in registry:
            raise KeyError(f"unknown classifier {name!r}; configured: {', '.join(registry)}")
    selected = [(name, registry[name]) for name in (models or list(registry))]
    scope = [i for i in items if i.split == split]
    written: dict[Path, int] = {}
    for name, classify in selected:
        groups: dict[tuple[str, str], list[ModelOutput]] = defaultdict(list)
        for p in classify(scope):
            groups[(p.model, p.prompt_version)].append(p)
        for outputs in groups.values():
            written[write_outputs(cache_dir, outputs)] = len(outputs)
        # token usage per task, when the classifier reports it (classify.eval_adapter)
        usage = getattr(classify, "usage_by_task", None)
        if usage:
            write_usage(cache_dir, name, split, usage, getattr(classify, "refreshed_at", ""))
    return written
