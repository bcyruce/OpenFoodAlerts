"""Metric definitions of the eval harness (spec §7.2), in plain Python.

Implemented here rather than called from scikit-learn so the definitions are explicit and
the unit tests can check them against scikit-learn independently.

Parameter names follow the ML shorthand: `gold` is the human Label of each item, `pred` the
model output (an AI classification of the eval item).

- A model output is a label or ABSTAIN. ABSTAIN is never a Label, so an abstention is
  always wrong: accuracy is over all scored items, abstentions included. The abstention
  rate and the coverage-accuracy curve report the abstentions separately.
- Macro / weighted F1 average over the labels that occur in the Labels or the outputs
  (scikit-learn's default label set), ABSTAIN excluded. A label that is output but never
  the Label has F1 0; a 0/0 precision or recall counts as 0.
"""

import random
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any, TypedDict

ABSTAIN = "abstain"
# self-reported confidence levels, most confident first (spec §6.3)
CONFIDENCES = ("high", "medium", "low")
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261025


def _check(gold: Sequence[str], pred: Sequence[str]) -> None:
    if len(gold) != len(pred):
        raise ValueError("gold and predictions differ in length")


def accuracy(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    _check(gold, pred)
    if not gold:
        return None
    return sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold)


def _labels(gold: Sequence[str], pred: Sequence[str]) -> list[str]:
    return sorted((set(gold) | set(pred)) - {ABSTAIN})


def _prf_all(
    gold: Sequence[str], pred: Sequence[str]
) -> dict[str, tuple[float, float, float, int]]:
    """label -> (precision, recall, F1, support), one pass over the items."""
    _check(gold, pred)
    tp: Counter[str] = Counter()
    for g, p in zip(gold, pred, strict=True):
        if g == p:
            tp[g] += 1
    predicted, support = Counter(pred), Counter(gold)
    out = {}
    for label in _labels(gold, pred):
        precision = tp[label] / predicted[label] if predicted[label] else 0.0
        recall = tp[label] / support[label] if support[label] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[label] = (precision, recall, f1, support[label])
    return out


def macro_f1(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    scores = _prf_all(gold, pred)
    if not gold or not scores:
        return None
    return sum(f1 for _, _, f1, _ in scores.values()) / len(scores)


def weighted_f1(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    scores = _prf_all(gold, pred)
    if not gold:
        return None
    return sum(f1 * support for _, _, f1, support in scores.values()) / len(gold)


def per_class(gold: Sequence[str], pred: Sequence[str]) -> dict[str, dict[str, float | int]]:
    """Precision, recall, F1 and gold support per label (sorted by label)."""
    return {
        label: {"precision": p, "recall": r, "f1": f, "support": s}
        for label, (p, r, f, s) in _prf_all(gold, pred).items()
    }


class ConfusionMatrix(TypedDict):
    labels: list[str]
    matrix: list[list[int]]


def confusion(
    gold: Sequence[str], pred: Sequence[str], *, order: Sequence[str] = ()
) -> ConfusionMatrix:
    """Square matrix, rows = gold, columns = predicted; labels in `order` first (e.g. the
    taxonomy order), then the remaining ones sorted, ABSTAIN last (its row is all zeros)."""
    _check(gold, pred)
    present = set(_labels(gold, pred))
    labels = [label for label in order if label in present]
    labels += sorted(present - set(labels))
    labels.append(ABSTAIN)
    index = {label: i for i, label in enumerate(labels)}
    counts = Counter(zip(gold, pred, strict=True))
    matrix = [[0] * len(labels) for _ in labels]
    for (g, p), n in counts.items():
        matrix[index[g]][index[p]] += n
    return {"labels": labels, "matrix": matrix}


def abstention_rate(pred: Sequence[str]) -> float | None:
    if not pred:
        return None
    return sum(p == ABSTAIN for p in pred) / len(pred)


def coverage_accuracy(
    gold: Sequence[str], pred: Sequence[str], confidence: Sequence[str | None]
) -> list[dict[str, Any]]:
    """One point per confidence level: answer only when confidence >= that level.

    coverage = answered items / all items; accuracy = correct / answered (None if no item
    is answered). Abstentions are never answered; a missing confidence counts as low.
    """
    _check(gold, pred)
    rank = [CONFIDENCES.index(c) if c in CONFIDENCES else len(CONFIDENCES) - 1 for c in confidence]
    points = []
    for level, name in enumerate(CONFIDENCES):
        covered = [
            g == p for g, p, r in zip(gold, pred, rank, strict=True) if p != ABSTAIN and r <= level
        ]
        points.append(
            {
                "min_confidence": name,
                "coverage": len(covered) / len(gold) if gold else None,
                "accuracy": sum(covered) / len(covered) if covered else None,
                "n": len(covered),
            }
        )
    return points


Statistic = Callable[[Sequence[str], Sequence[str]], float | None]


def bootstrap_ci(
    gold: Sequence[str],
    pred: Sequence[str],
    statistic: Statistic,
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
    level: float = 0.95,
) -> list[float] | None:
    """Percentile bootstrap interval: resample items with replacement `resamples` times
    (Python's `random` seeded with `seed`, so a run is reproducible on every platform)."""
    _check(gold, pred)
    if not gold:
        return None
    rng = random.Random(seed)
    n = len(gold)
    positions = range(n)
    values = []
    for _ in range(resamples):
        idx = rng.choices(positions, k=n)
        value = statistic([gold[i] for i in idx], [pred[i] for i in idx])
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    alpha = (1 - level) / 2
    return [_quantile(values, alpha), _quantile(values, 1 - alpha)]


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's kappa of two annotators; None when undefined (no items, chance agreement 1)."""
    _check(a, b)
    n = len(a)
    if not n:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[c] * count_b[c] for c in count_a) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


# --- T3 / T4 ------------------------------------------------------------------------

NO_HAZARD = "none"
UNKNOWN_COUNTRY = "unknown"


def normalize_span(text: str) -> str:
    """T3 normalized form: NFKC, casefold, punctuation -> space, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)
    return " ".join(text.split())


def span_match(pred: str, gold: str) -> tuple[bool, bool]:
    """(exact, normalized) match of a T3 prediction. Gold "none" means the text names no
    Hazard: only an abstention matches it, and an abstention matches nothing else."""
    if gold == NO_HAZARD or pred == ABSTAIN:
        both = gold == NO_HAZARD and pred == ABSTAIN
        return both, both
    return pred == gold, normalize_span(pred) == normalize_span(gold)


# EU / RASFF codes that are not ISO 3166-1 alpha-2
_COUNTRY_ALIASES = {"UK": "GB", "EL": "GR", "XI": "GB"}


@cache
def _country_names() -> dict[str, str]:
    from openfoodalerts.sources.rasff.lookups import Dictionary, normalize_name, read_seed

    return {
        normalize_name(e.name): _COUNTRY_ALIASES.get(e.code, e.code)
        for e in read_seed(Dictionary.COUNTRY)
        if e.code and len(e.code) == 2
    }


def to_iso2(value: str) -> str:
    """T4 normalized form: an ISO2 code (EU aliases and English RASFF country names mapped),
    else the casefolded text; empty, "unknown" and an abstention are all "unknown"."""
    text = " ".join(value.split())
    if not text or text.casefold() in (UNKNOWN_COUNTRY, ABSTAIN):
        return UNKNOWN_COUNTRY
    if len(text) == 2 and text.isalpha():
        return _COUNTRY_ALIASES.get(text.upper(), text.upper())
    return _country_names().get(text.casefold(), text.casefold())


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default method)."""
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)
