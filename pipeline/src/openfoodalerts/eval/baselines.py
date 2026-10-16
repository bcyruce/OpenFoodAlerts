"""T1 baselines (spec §7.2), scored by the harness exactly like a model's cached outputs.

1. Keyword rules (`baseline-keywords`, prompt_version `kw1`): the ticket 12 rules of
   `keywords.py` guess a RASFF Hazard category, which the taxonomy maps to a T1 label. A
   match in the hazard-bearing fields (recall reason, title + summary, subject) is
   confidence high, a match elsewhere in the input medium, no match abstains. The evidence
   span is the matched text. Note: the NVWA / openFDA strata of the eval sample are these
   same rules, so this baseline is scored on a sample stratified by its own output.
2. TF-IDF + LogisticRegression (`baseline-tfidf-lr`, prompt_version `silver1`): trained on
   the RASFF silver set (subject -> label) and applied to the eval items' whole input. It
   never abstains; confidence from the predicted probability (>= 0.6 high, >= 0.3 medium,
   else low). The silver subjects are mostly English one-liners, while NVWA items are
   Dutch pages and openFDA items long English recall texts: expect a domain and language
   shift. Character n-grams (2-5, within word boundaries) soften the language gap a little
   (Listeria, Salmonella, aflatoxine, allergenen share n-grams across languages).

Both are deterministic: no randomness in the rules, a fixed random_state for the model.
"""

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import ModelOutput
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.keywords import HAZARD_FIELDS, RULES
from openfoodalerts.eval.labelset import Taxonomy

TASK = "hazard_category"
KEYWORD_MODEL = "baseline-keywords"
KEYWORD_VERSION = "kw1"
TFIDF_MODEL = "baseline-tfidf-lr"
TFIDF_VERSION = "silver1"
SCHEMA_VERSION = "1"
RANDOM_STATE = 20261025
HIGH, MEDIUM = 0.6, 0.3


class InsufficientTraining(ValueError):
    """The silver set has fewer than two labels; nothing to learn."""


def _output(
    item: ItemRow,
    *,
    model: str,
    prompt_version: str,
    taxonomy: Taxonomy,
    created_at: str,
    value: str | None,
    confidence: str | None,
    evidence_span: str | None = None,
) -> ModelOutput:
    return ModelOutput(
        item_id=item.item_id,
        task=TASK,
        value=value,
        confidence=confidence if value is not None else None,
        abstained=value is None,
        evidence_span=evidence_span,
        input_hash=input_hash(
            item.input,
            prompt_version=prompt_version,
            model=model,
            taxonomy_version=taxonomy.version,
        ),
        model=model,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        taxonomy_version=taxonomy.version,
        created_at=created_at,
    )


def _first_rule(text: str) -> tuple[str, str] | None:
    for category, pattern in RULES:
        match = pattern.search(text)
        if match:
            return category, match.group(0)
    return None


def keyword_outputs(
    items: Iterable[ItemRow], taxonomy: Taxonomy, *, created_at: str
) -> list[ModelOutput]:
    out = []
    for item in items:
        primary = "\n".join(v for k, v in item.input.items() if k in HAZARD_FIELDS and v)
        hit, confidence = _first_rule(primary), "high"
        if hit is None:
            hit, confidence = _first_rule("\n".join(v for v in item.input.values() if v)), "medium"
        label = taxonomy.label_for_name(hit[0]) if hit else None
        out.append(
            _output(
                item,
                model=KEYWORD_MODEL,
                prompt_version=KEYWORD_VERSION,
                taxonomy=taxonomy,
                created_at=created_at,
                value=label,
                confidence=confidence,
                evidence_span=hit[1] if hit and label else None,
            )
        )
    return out


def read_silver(path: Path, taxonomy: Taxonomy) -> list[tuple[str, str]]:
    """(subject, label) pairs of eval/silver.csv whose label is in the taxonomy."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [
            (r["subject"], r["label"]) for r in csv.DictReader(f) if r["label"] in taxonomy.labels
        ]


def _text(item: ItemRow) -> str:
    return "\n".join(v for v in item.input.values() if v)


def tfidf_outputs(
    items: Sequence[ItemRow],
    silver: Sequence[tuple[str, str]],
    taxonomy: Taxonomy,
    *,
    created_at: str,
) -> list[ModelOutput]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    if len({label for _, label in silver}) < 2:
        raise InsufficientTraining("the silver set needs at least two labels")
    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True),
        LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE),
    )
    model.fit([s for s, _ in silver], [label for _, label in silver])
    if not items:
        return []
    probabilities = model.predict_proba([_text(i) for i in items])
    classes = [str(c) for c in model.classes_]
    out = []
    for item, row in zip(items, probabilities, strict=True):
        best = max(range(len(classes)), key=lambda k: (row[k], -k))
        p = float(row[best])
        out.append(
            _output(
                item,
                model=TFIDF_MODEL,
                prompt_version=TFIDF_VERSION,
                taxonomy=taxonomy,
                created_at=created_at,
                value=classes[best],
                confidence="high" if p >= HIGH else "medium" if p >= MEDIUM else "low",
            )
        )
    return out
