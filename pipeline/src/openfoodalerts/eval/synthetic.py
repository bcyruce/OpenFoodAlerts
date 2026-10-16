"""A synthetic example report, `eval/results/example.json`, so the /evaluation page
(ticket 25) can be built before any real Label or model output exists.

**Everything in it is made up**: Labels are invented from the sampling strata (the keyword
pre-label, or the official RASFF category) with 15% seeded noise, so the keyword baseline
and the noise audit look better than they will on real Labels; "synthetic-model" is a
seeded corruption of those Labels. Only the items and the two baselines' outputs are
real; the baselines are scored against the invented Labels. The report carries
`"synthetic": true` and `"git_sha": "synthetic"`. It is produced by the same `build_report`
as latest.json, so it always has the current shape. Reproducible: no clock, fixed seeds.
"""

import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import ModelOutput
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.harness import RunInput, baseline_runs, build_report, merge_other_split
from openfoodalerts.eval.labeling import NO_HAZARD, UNKNOWN_COUNTRY, UNSURE
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.eval.metrics import CONFIDENCES

SYNTHETIC_MODEL = "synthetic-model"
SYNTHETIC_PROMPT = "v0"
CREATED_AT = "2026-10-26T00:00:00+00:00"
SEED = 20261025
PRODUCT_CATEGORIES = (
    "cereals and bakery products",
    "cocoa and cocoa preparations, coffee and tea",
    "confectionery",
    "fruits and vegetables",
    "meat and meat products (other than poultry)",
    "milk and milk products",
    "nuts, nut products and seeds",
    "prepared dishes and snacks",
)
COUNTRIES = ("NL", "DE", "BE", "US", "CN", "TR", "IT", "MX")
# hazard-bearing input field per Source, the source of the invented T3 span
SPAN_FIELD = {"openfda": "reason_for_recall", "nvwa": "title", "rasff": "subject"}


def _rng(*parts: object) -> random.Random:
    return random.Random(":".join(str(p) for p in (SEED, *parts)))


def _t1(item: ItemRow, taxonomy: Taxonomy, rng: random.Random) -> str:
    official = [taxonomy.label_for_name(c) for c in item.official_categories]
    group = item.stratum.split(":", 1)[-1]
    label = next((x for x in official if x), None) or (
        group if group in taxonomy.labels else rng.choice(taxonomy.labels)
    )
    # the pre-label is the keyword baseline's own output (and the official category is
    # what the noise audit compares with): disagree with it now and then
    return rng.choice(taxonomy.labels) if rng.random() < 0.15 else label


def _labels(item: ItemRow, taxonomy: Taxonomy) -> dict[str, str]:
    rng = _rng(item.item_id, "A")
    span = item.input.get(SPAN_FIELD[item.source], "")
    t1 = _t1(item, taxonomy, rng)
    return {
        "item_id": item.item_id,
        "annotator": "A",
        "guideline_version": "v1",
        "hazard_category": UNSURE if rng.random() < 0.03 else t1,
        "product_category": rng.choice(PRODUCT_CATEGORIES),
        "hazard": span if span and rng.random() < 0.9 else NO_HAZARD,
        "origin_country": rng.choice(COUNTRIES) if rng.random() < 0.3 else UNKNOWN_COUNTRY,
        "product_type": rng.choices(("food", "feed", "food contact material"), weights=(90, 5, 5))[
            0
        ],
        "note": "synthetic",
        "labelled_at": CREATED_AT,
    }


def _second_annotator(a: dict[str, str], taxonomy: Taxonomy) -> dict[str, str]:
    rng = _rng(a["item_id"], "B")
    b = a | {"annotator": "B"}
    if rng.random() < 0.15:
        b["hazard_category"] = rng.choice(taxonomy.labels)
    if rng.random() < 0.25:
        b["product_category"] = rng.choice(PRODUCT_CATEGORIES)
    return b


def _model_value(
    item: ItemRow, task: str, gold: str, taxonomy: Taxonomy
) -> tuple[str | None, str | None]:
    """(value or None for abstain, confidence): right more often when confident."""
    rng = _rng(item.item_id, task, "model")
    if rng.random() < 0.06:
        return None, None
    skill = {"rasff": 0.65, "nvwa": 0.8, "openfda": 0.85}[item.source]
    right = rng.random() < skill
    confidence = rng.choices(CONFIDENCES, weights=(70, 20, 10) if right else (35, 35, 30))[0]
    if task == "hazard":
        if gold == NO_HAZARD or not right:
            words = item.input.get(SPAN_FIELD[item.source], "").split()
            return (words[0] if words else None), confidence
        return (gold if rng.random() < 0.75 else gold.casefold().rstrip(".") + "."), confidence
    if right or gold == UNSURE:
        return gold, confidence
    choices = {
        "hazard_category": taxonomy.labels,
        "product_category": PRODUCT_CATEGORIES,
        "origin_country": (UNKNOWN_COUNTRY, *COUNTRIES),
        "product_type": ("food", "feed", "food contact material"),
    }[task]
    return rng.choice([c for c in choices if c != gold] or list(choices)), confidence


def _model_outputs(
    items: Sequence[ItemRow], labels: dict[str, dict[str, str]], taxonomy: Taxonomy
) -> list[ModelOutput]:
    out = []
    for item in items:
        h = input_hash(
            item.input,
            prompt_version=SYNTHETIC_PROMPT,
            model=SYNTHETIC_MODEL,
            taxonomy_version=taxonomy.version,
        )
        for task in ("hazard_category", "product_category", "hazard", "origin_country"):
            value, confidence = _model_value(item, task, labels[item.item_id][task], taxonomy)
            out.append(
                ModelOutput(
                    item_id=item.item_id,
                    task=task,
                    value=value,
                    confidence=confidence,
                    abstained=value is None,
                    evidence_span=None,
                    input_hash=h,
                    model=SYNTHETIC_MODEL,
                    prompt_version=SYNTHETIC_PROMPT,
                    schema_version="1",
                    taxonomy_version=taxonomy.version,
                    created_at=CREATED_AT,
                )
            )
        value, confidence = _model_value(
            item, "product_type", labels[item.item_id]["product_type"], taxonomy
        )
        out.append(
            ModelOutput(
                item.item_id,
                "product_type",
                value,
                confidence,
                value is None,
                None,
                h,
                SYNTHETIC_MODEL,
                SYNTHETIC_PROMPT,
                "1",
                taxonomy.version,
                CREATED_AT,
            )
        )
    return out


def example_report(
    items: Sequence[ItemRow], taxonomy: Taxonomy, silver_path: Path
) -> dict[str, Any]:
    a = {i.item_id: _labels(i, taxonomy) for i in items}
    labels = list(a.values()) + [
        _second_annotator(a[i.item_id], taxonomy) for i in items if i.agreement
    ]
    model = RunInput(SYNTHETIC_MODEL, SYNTHETIC_PROMPT, "model", _model_outputs(items, a, taxonomy))
    report: dict[str, Any] | None = None
    for split in ("test", "dev"):
        runs, _ = baseline_runs(
            [i for i in items if i.split == split], silver_path, taxonomy, created_at=CREATED_AT
        )
        current = build_report(
            items,
            labels,
            [model, *runs],
            taxonomy,
            split=split,
            git_sha="synthetic",
            created_at=CREATED_AT,
            synthetic=True,
        )
        report = merge_other_split(current, report, split)
    assert report is not None
    return report
