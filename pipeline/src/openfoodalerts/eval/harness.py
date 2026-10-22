"""The eval harness behind `make eval` (spec §7.2-7.3): offline, no paid API, no network.

Inputs: eval/items.csv, eval/labels.csv (annotator A's Labels count, see labels.py), the
cached model outputs eval/cache/{model}/{prompt_version}.jsonl and the two T1 baselines
(computed on the
fly from the committed files, see baselines.py). Output: eval/results/latest.json, plus one
`eval_runs` row per (model or baseline, task, split) when a database is reachable.

Scoring rules (see eval/README.md "Metrics" for the full list):

- One split per run: dev unless test is asked for explicitly. Runs of the other split
  already in latest.json are kept, so dev and test results live side by side.
- Tasks and Sources: T1 on all three Sources (RASFF from the subject only); T2-T5 on NVWA and
  openFDA (spec §6.1). Items without a Label for a task are left out of that task.
- A missing model output, or a cached one whose input_hash no longer matches the item's
  frozen input, counts as an abstention (n_missing / n_stale say how many).
- T1, T2, T5: classification metrics of metrics.py (abstention = wrong), per Source and
  overall, with bootstrap CIs; per-class scores and the confusion matrix overall.
- T3: exact and normalized span match; a Label "none" is matched by an abstention only.
- T4: exact match and match after ISO2 normalization; an abstention means "unknown".
- Agreement (Cohen's kappa, A vs B) and the noise audit (A vs the official RASFF
  categories) use every flagged item regardless of split: they compare Labels, not models.
"""

import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval import baselines, metrics
from openfoodalerts.eval.cache import ModelOutput, read_cache
from openfoodalerts.eval.factcheck import FACTCHECK_FILE, factcheck_report, read_factcheck
from openfoodalerts.eval.files import ItemRow, read_items, read_labels
from openfoodalerts.eval.labeling import PRODUCT_TYPES
from openfoodalerts.eval.labels import label_value, latest_labels
from openfoodalerts.eval.labelset import Taxonomy, load_taxonomy
from openfoodalerts.eval.metrics import ABSTAIN

SOURCES = ("nvwa", "openfda", "rasff")
SPLITS = ("dev", "test")
TASK_ORDER = ("hazard_category", "product_category", "hazard", "origin_country", "product_type")
TASK_SOURCES: dict[str, tuple[str, ...]] = {
    "hazard_category": SOURCES,
    "product_category": ("nvwa", "openfda"),
    "hazard": ("nvwa", "openfda"),
    "origin_country": ("nvwa", "openfda"),
    "product_type": ("nvwa", "openfda"),
}
CLASSIFICATION_TASKS = ("hazard_category", "product_category", "product_type")
# Tasks whose outputs depend on the T1 taxonomy (its version is part of their input_hash).
TAXONOMY_TASKS = ("hazard_category",)
KAPPA_TASKS = ("hazard_category", "product_category", "origin_country", "product_type")


@dataclass(frozen=True)
class RunInput:
    """The outputs of one model (or baseline) and prompt version."""

    model: str
    prompt_version: str
    kind: str  # "model" or "baseline"
    outputs: Sequence[ModelOutput]


@dataclass(frozen=True)
class _Scored:
    source: str
    gold: str
    pred: str  # ABSTAIN when abstained, missing or stale
    confidence: str | None
    missing: bool
    stale: bool


def _taxonomy_version(version: str) -> int | str:
    return int(version) if version.isdigit() else version


def _classification_block(rows: Sequence[_Scored], seed: int) -> dict[str, Any]:
    gold = [r.gold for r in rows]
    pred = [r.pred for r in rows]
    answered = [g == p for g, p in zip(gold, pred, strict=True) if p != ABSTAIN]
    return {
        "n": len(rows),
        "accuracy": metrics.accuracy(gold, pred),
        "accuracy_ci95": metrics.bootstrap_ci(gold, pred, metrics.accuracy, seed=seed),
        "accuracy_answered": sum(answered) / len(answered) if answered else None,
        "macro_f1": metrics.macro_f1(gold, pred),
        "macro_f1_ci95": metrics.bootstrap_ci(gold, pred, metrics.macro_f1, seed=seed),
        "weighted_f1": metrics.weighted_f1(gold, pred),
        "abstention_rate": metrics.abstention_rate(pred),
        "coverage_accuracy": metrics.coverage_accuracy(gold, pred, [r.confidence for r in rows]),
        **_counts(rows),
    }


def _match_rate(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _span_block(rows: Sequence[_Scored], task: str, seed: int) -> dict[str, Any]:
    if task == "hazard":
        matches = [metrics.span_match(r.pred, r.gold) for r in rows]
    else:  # origin_country: an abstention is "unknown"
        matches = [
            (
                (r.pred if r.pred != ABSTAIN else metrics.UNKNOWN_COUNTRY) == r.gold,
                metrics.to_iso2(r.pred) == metrics.to_iso2(r.gold),
            )
            for r in rows
        ]
    exact = ["1" if e else "0" for e, _ in matches]
    normalized = ["1" if n else "0" for _, n in matches]
    ones = ["1"] * len(rows)
    return {
        "n": len(rows),
        "exact_match": _match_rate([e for e, _ in matches]),
        "exact_match_ci95": metrics.bootstrap_ci(ones, exact, metrics.accuracy, seed=seed),
        "normalized_match": _match_rate([n for _, n in matches]),
        "normalized_match_ci95": metrics.bootstrap_ci(
            ones, normalized, metrics.accuracy, seed=seed
        ),
        "abstention_rate": metrics.abstention_rate([r.pred for r in rows]),
        **_counts(rows),
    }


def _counts(rows: Sequence[_Scored]) -> dict[str, int]:
    return {"n_missing": sum(r.missing for r in rows), "n_stale": sum(r.stale for r in rows)}


def _order(task: str, taxonomy: Taxonomy) -> Sequence[str]:
    if task == "hazard_category":
        return taxonomy.labels
    if task == "product_type":
        return PRODUCT_TYPES
    return ()


def _score_task(
    run: RunInput,
    task: str,
    items: Sequence[ItemRow],
    label_rows: Mapping[str, Mapping[str, str]],
    taxonomy: Taxonomy,
    seed: int,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    by_item = {p.item_id: p for p in run.outputs if p.task == task}
    rows: list[_Scored] = []
    excluded = {"n_unsure": 0, "n_unlabelled": 0}
    for it in items:
        if it.source not in TASK_SOURCES[task]:
            continue
        label_row = label_rows.get(it.item_id)
        gold = label_value(label_row, task)
        if gold is None:
            unsure = label_row is not None and (label_row.get(task) or "").strip() == "unsure"
            excluded["n_unsure" if unsure else "n_unlabelled"] += 1
            continue
        p = by_item.get(it.item_id)
        expected = input_hash(
            it.input,
            prompt_version=run.prompt_version,
            model=run.model,
            # only T1 has a taxonomy; T2-T5 hash with an empty taxonomy version
            taxonomy_version=taxonomy.version if task in TAXONOMY_TASKS else "",
        )
        stale = p is not None and p.input_hash != expected
        usable = p is not None and not stale
        value = p.value if usable and p is not None and not p.abstained else None
        rows.append(
            _Scored(
                source=it.source,
                gold=gold,
                pred=value if value is not None else ABSTAIN,
                confidence=p.confidence if usable and p is not None else None,
                missing=p is None,
                stale=stale,
            )
        )
    if not rows:
        return None, excluded

    def block(subset: Sequence[_Scored]) -> dict[str, Any]:
        if task in CLASSIFICATION_TASKS:
            return _classification_block(subset, seed)
        return _span_block(subset, task, seed)

    overall = block(rows) | excluded
    result: dict[str, Any] = {
        "model": run.model,
        "prompt_version": run.prompt_version,
        "kind": run.kind,
        "split": "",
        "task": task,
        "schema_version": ",".join(sorted({p.schema_version for p in by_item.values()})),
        "taxonomy_version": _taxonomy_version(taxonomy.version),
        "by_source": {s: block([r for r in rows if r.source == s]) for s in TASK_SOURCES[task]},
        "overall": overall,
    }
    if task in CLASSIFICATION_TASKS:
        golds = [r.gold for r in rows]
        preds = [r.pred for r in rows]
        result["per_class"] = metrics.per_class(golds, preds)
        result["confusion_matrix"] = metrics.confusion(golds, preds, order=_order(task, taxonomy))
    return result, excluded


def _agreement(items: Sequence[ItemRow], labels: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    a, b = latest_labels(labels, "A"), latest_labels(labels, "B")
    subset = [i.item_id for i in items if i.agreement]
    by_task: dict[str, dict[str, Any]] = {}
    for task in KAPPA_TASKS:
        pairs = []
        for item_id in subset:
            va, vb = label_value(a.get(item_id), task), label_value(b.get(item_id), task)
            if va is not None and vb is not None:
                if task == "origin_country":
                    va, vb = metrics.to_iso2(va), metrics.to_iso2(vb)
                pairs.append((va, vb))
        by_task[task] = {
            "cohens_kappa": metrics.cohens_kappa([x for x, _ in pairs], [y for _, y in pairs]),
            "n": len(pairs),
        }
    t1 = by_task["hazard_category"]
    return {
        "cohens_kappa": t1["cohens_kappa"],
        "n": t1["n"],
        "task": "hazard_category",
        "subset_size": len(subset),
        "by_task": by_task,
    }


def _noise_audit(
    items: Sequence[ItemRow], labels: Sequence[Mapping[str, str]], taxonomy: Taxonomy
) -> dict[str, Any]:
    a = latest_labels(labels, "A")
    agree: list[bool] = []
    counts = {"n_unsure": 0, "n_unmapped": 0, "n_multi_label": 0}
    for it in items:
        if not it.noise_audit or it.item_id not in a:
            continue
        mine = label_value(a[it.item_id], "hazard_category")
        if mine is None:
            counts["n_unsure"] += 1
            continue
        official = {taxonomy.label_for_name(c) for c in it.official_categories} - {None}
        if not official:
            counts["n_unmapped"] += 1
            continue
        counts["n_multi_label"] += len(official) > 1
        agree.append(mine in official)
    return {"agreement_with_official": _match_rate(agree), "n": len(agree), **counts}


def _label_status(
    items: Sequence[ItemRow], labels: Sequence[Mapping[str, str]]
) -> dict[str, dict[str, int]]:
    a = latest_labels(labels, "A")
    return {
        split: {
            "items": sum(i.split == split for i in items),
            "labelled": sum(i.split == split and i.item_id in a for i in items),
        }
        for split in SPLITS
        if any(i.split == split for i in items)
    }


def build_report(
    items: Sequence[ItemRow],
    labels: Sequence[Mapping[str, str]],
    runs: Iterable[RunInput],
    taxonomy: Taxonomy,
    *,
    split: str,
    git_sha: str,
    created_at: str,
    synthetic: bool = False,
    seed: int = metrics.BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)}")
    scored_items = [i for i in items if i.split == split]
    label_rows = latest_labels(labels, "A")
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for run in runs:
        tasks = {p.task for p in run.outputs}
        for task in (t for t in TASK_ORDER if t in tasks):
            result, _ = _score_task(run, task, scored_items, label_rows, taxonomy, seed)
            if result is None:
                skipped.append(
                    {
                        "model": run.model,
                        "prompt_version": run.prompt_version,
                        "split": split,
                        "task": task,
                        "reason": "no Labels",
                    }
                )
                continue
            result["split"] = split
            results.append(result)
    return {
        "git_sha": git_sha,
        "created_at": created_at,
        "taxonomy_version": _taxonomy_version(taxonomy.version),
        "synthetic": synthetic,
        "bootstrap": {"resamples": metrics.BOOTSTRAP_RESAMPLES, "seed": seed, "level": 0.95},
        "label_status": _label_status(items, labels),
        "runs": results,
        "skipped": skipped,
        "agreement": _agreement(items, labels),
        "noise_audit": _noise_audit(items, labels, taxonomy),
    }


def merge_other_split(
    report: dict[str, Any], previous: Mapping[str, Any] | None, split: str
) -> dict[str, Any]:
    """The report plus the runs (and skipped entries) of the other split from the previous
    latest.json, so a test run does not erase dev results and vice versa. The decisions
    written by `ofa eval-threshold` and `ofa eval-compare` (DECISION_KEYS) are kept too:
    they are re-made by those commands, not by scoring."""
    if not previous:
        return report
    keep = [r for r in previous.get("runs", []) if r.get("split") != split]
    keep_skipped = [s for s in previous.get("skipped", []) if s.get("split") != split]
    decisions = {k: previous[k] for k in DECISION_KEYS if k in previous}
    return (
        report
        | decisions
        | {"runs": keep + report["runs"], "skipped": keep_skipped + report["skipped"]}
    )


# Top-level keys of latest.json that hold decisions made on dev (ticket 21).
DECISION_KEYS = ("thresholds", "model_selection")


def baseline_runs(
    items: Sequence[ItemRow], silver_path: Path, taxonomy: Taxonomy, *, created_at: str
) -> tuple[list[RunInput], list[str]]:
    """Both T1 baselines, or a notice for the TF-IDF one when the silver set cannot train it."""
    runs = [
        RunInput(
            baselines.KEYWORD_MODEL,
            baselines.KEYWORD_VERSION,
            "baseline",
            baselines.keyword_outputs(items, taxonomy, created_at=created_at),
        )
    ]
    notices = []
    silver = baselines.read_silver(silver_path, taxonomy)
    try:
        tfidf = baselines.tfidf_outputs(items, silver, taxonomy, created_at=created_at)
    except baselines.InsufficientTraining as exc:
        notices.append(f"{baselines.TFIDF_MODEL} skipped: {exc} ({len(silver)} rows)")
    else:
        runs.append(RunInput(baselines.TFIDF_MODEL, baselines.TFIDF_VERSION, "baseline", tfidf))
    return runs, notices


def run_eval(
    eval_dir: Path,
    *,
    split: str,
    taxonomy_path: Path,
    output: Path,
    created_at: str,
    git_sha: str,
    cache_dir: Path | None = None,
    synthetic: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Score the cache and the baselines on one split and write the report to `output`
    (keeping the other split's runs found there). Returns the report and notices."""
    taxonomy = load_taxonomy(taxonomy_path)
    items = read_items(eval_dir / "items.csv")
    labels = read_labels(eval_dir / "labels.csv")
    runs, notices = baseline_runs(
        [i for i in items if i.split == split],
        eval_dir / "silver.csv",
        taxonomy,
        created_at=created_at,
    )
    cache = read_cache(cache_dir or eval_dir / "cache")
    for cached in cache:
        runs.append(RunInput(cached.model, cached.prompt_version, "model", cached.outputs))
    report = build_report(
        items,
        labels,
        runs,
        taxonomy,
        split=split,
        git_sha=git_sha,
        created_at=created_at,
        synthetic=synthetic,
    )
    # T6 (ticket 18): the human fact-check of summaries, all splits (eval/factcheck/t6.csv)
    report["t6_factcheck"] = factcheck_report(
        read_factcheck(eval_dir / FACTCHECK_FILE),
        items,
        [o for cached in cache for o in cached.outputs],
    )
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    report = merge_other_split(report, previous, split)
    write_report(output, report)
    return report, notices


def current_git_sha(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
