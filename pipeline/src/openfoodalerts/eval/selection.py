"""Decisions made on the dev split (ticket 21): the "low confidence" threshold per task
(spec §6.3) and the model (spec §6.4). Pure functions over a latest.json report;
`ofa eval-threshold` and `ofa eval-compare` write their results back into it.

**Threshold rule** (`choose_threshold`): the coverage-accuracy curve of a run has one
point per confidence level: answer only items with confidence ≥ the level (high; high +
medium; all). The chosen `min_confidence` is the level with the **widest coverage whose
accuracy (correct / answered) is at least the target** (default 0.90), counting only
levels with at least `min_n` answered items. If no level reaches the target, `high` is
chosen (only high-confidence answers are accepted without review) and `met_target` is
false. An empty curve (no Labels, n = 0) chooses nothing. The threshold controls the
review queue only (results below it are queued, abstains always are); AI fields are
shown at once either way (spec §6.5). Ties cannot happen: coverage grows with each level.

**Model rule** (`select_model`, spec §6.4): T1 hazard_category, overall dev macro-F1 of
each candidate's newest prompt version. The default is Claude Haiku 5.5; if the
challenger's (DeepSeek Flash, which replaced GPT-5 mini) macro-F1 is at least Haiku's minus
2 points (a gap of exactly 2 points counts as within), the cheaper of the two is chosen.
Cheaper = lower cost per request at standard prices (eval/model_prices.json; for DeepSeek
the peak price, with the off-peak cost as a notice) from the token usage measured by
`make eval-refresh` on dev (eval/cache/{model}/usage.json, all tasks), or from a nominal
profile (`prices.NOMINAL_REQUEST`) when either model has no measured usage. Without a dev
run with n > 0 for both, the comparison is `pending` and the default stands. A challenger
that is more than 2 points *better* but dearer is not chosen by this rule; that case is
flagged as a notice for the owner.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from openfoodalerts.classify.model import Usage
from openfoodalerts.eval.gate import newest_runs
from openfoodalerts.eval.prices import NOMINAL_REQUEST, Rates, cost_usd

TARGET_ACCURACY = 0.90
MIN_N = 1
MAX_GAP = 0.02
SPLIT = "dev"
SELECTION_TASK = "hazard_category"
DEFAULT_MODEL = "claude-haiku-5-5"
CHALLENGER = "deepseek-flash"
# The tasks whose eval blocks have a coverage-accuracy curve (classification blocks).
CURVE_TASKS = ("hazard_category", "product_category", "product_type")
LEVELS = ("high", "medium", "low")


@dataclass(frozen=True)
class ThresholdChoice:
    min_confidence: str
    met_target: bool
    coverage: float | None
    accuracy: float | None
    n: int


def choose_threshold(
    curve: Sequence[Mapping[str, Any]], *, target_accuracy: float, min_n: int = MIN_N
) -> ThresholdChoice | None:
    """The threshold rule (module docstring); None for a curve without answers."""
    by_level = {p["min_confidence"]: p for p in curve}
    usable = [
        by_level[level]
        for level in LEVELS
        if level in by_level and by_level[level].get("accuracy") is not None
    ]
    if not usable:
        return None
    meeting = [
        p for p in usable if p["n"] >= min_n and round(p["accuracy"] - target_accuracy, 9) >= 0
    ]
    if meeting:
        best = max(meeting, key=lambda p: (p["coverage"], LEVELS.index(p["min_confidence"])))
        met = True
    else:
        best = by_level.get("high") or usable[0]
        met = False
    return ThresholdChoice(
        best["min_confidence"], met, best.get("coverage"), best.get("accuracy"), best["n"]
    )


def _model_runs(report: Mapping[str, Any], task: str, split: str) -> dict[str, Mapping[str, Any]]:
    runs = [r for r in report.get("runs", []) if r.get("kind", "model") == "model"]
    return newest_runs({"runs": runs}, task, split)


def threshold_entries(
    report: Mapping[str, Any],
    *,
    model: str,
    tasks: Sequence[str],
    target_accuracy: float,
    min_n: int = MIN_N,
    split: str = SPLIT,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One `thresholds` entry per task with a usable dev curve of the model's newest
    prompt version, and a notice for every task without one."""
    entries: list[dict[str, Any]] = []
    notices: list[str] = []
    for task in tasks:
        run = _model_runs(report, task, split).get(model)
        if run is None:
            notices.append(f"{task}: no {split} run of {model}")
            continue
        curve = run["overall"].get("coverage_accuracy") or []
        choice = choose_threshold(curve, target_accuracy=target_accuracy, min_n=min_n)
        if choice is None:
            notices.append(
                f"{task}: {model}/{run['prompt_version']} has no answered {split} items"
                f" (n = {run['overall'].get('n', 0)})"
            )
            continue
        entries.append(
            {
                "model": model,
                "prompt_version": run["prompt_version"],
                "task": task,
                "min_confidence": choice.min_confidence,
                "split": split,
                "rule": "widest coverage with accuracy >= target_accuracy",
                "target_accuracy": target_accuracy,
                "met_target": choice.met_target,
                "coverage": choice.coverage,
                "accuracy": choice.accuracy,
                "n": choice.n,
            }
        )
        if not choice.met_target:
            notices.append(
                f"{task}: no level reaches accuracy {target_accuracy:.2f};"
                " only high-confidence answers are accepted without review"
            )
    return entries, notices


def merge_thresholds(
    existing: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """`existing` without the (model, prompt_version, task) entries in `new`, then `new`."""
    keys = {(e["model"], e["prompt_version"], e["task"]) for e in new}
    kept = [dict(e) for e in existing if (e["model"], e["prompt_version"], e["task"]) not in keys]
    return kept + [dict(e) for e in new]


def _per_request(usage: Usage) -> Usage:
    n = usage.requests or 1
    return Usage(
        1,
        round(usage.input_tokens / n),
        round(usage.output_tokens / n),
        round(usage.cache_creation_input_tokens / n),
        round(usage.cache_read_input_tokens / n),
    )


def select_model(
    report: Mapping[str, Any],
    *,
    prices: Mapping[str, Rates],
    usage: Mapping[str, Usage],
    decided_at: str,
    default: str = DEFAULT_MODEL,
    challenger: str = CHALLENGER,
    max_gap: float = MAX_GAP,
    split: str = SPLIT,
    task: str = SELECTION_TASK,
    shutdowns: Mapping[str, str] | None = None,
    off_peak: Mapping[str, Rates] | None = None,
) -> dict[str, Any]:
    """The `model_selection` block of latest.json (the model rule, module docstring).
    `prices` are the standard (for DeepSeek: peak) rates; `off_peak` the cheaper rates of
    models priced by the hour, reported beside them."""
    runs = _model_runs(report, task, split)
    notices: list[str] = []
    cheaper_hours = off_peak or {}
    measured = all(usage.get(m) and usage[m].requests for m in (default, challenger))
    if not measured:
        notices.append(
            "no measured dev token usage for both models (make eval-refresh writes"
            " eval/cache/{model}/usage.json); cost compared on a nominal request of"
            f" {NOMINAL_REQUEST.input_tokens} input, {NOMINAL_REQUEST.cache_read_input_tokens}"
            f" cached input and {NOMINAL_REQUEST.output_tokens} output tokens"
        )
    candidates = []
    for model in (default, challenger):
        run = runs.get(model)
        overall = run["overall"] if run else {}
        profile = _per_request(usage[model]) if measured else NOMINAL_REQUEST
        rates = prices.get(model)
        candidates.append(
            {
                "model": model,
                "prompt_version": run["prompt_version"] if run else None,
                "macro_f1": overall.get("macro_f1"),
                "macro_f1_ci95": overall.get("macro_f1_ci95"),
                "n": overall.get("n", 0),
                "cost_basis": "measured" if measured else "nominal",
                "tokens_per_request": {
                    "input": profile.input_tokens,
                    "cache_write": profile.cache_creation_input_tokens,
                    "cache_read": profile.cache_read_input_tokens,
                    "output": profile.output_tokens,
                },
                "cost_per_1000_requests_usd": (
                    None if rates is None else round(1000 * cost_usd(profile, rates), 6)
                ),
            }
        )
        if model in cheaper_hours:
            off = round(1000 * cost_usd(profile, cheaper_hours[model]), 6)
            candidates[-1]["cost_per_1000_requests_off_peak_usd"] = off
            notices.append(
                f"{model} is compared at its peak price; off-peak it costs ${off:g}"
                " per 1,000 requests (our timers do not keep to its off-peak hours)"
            )
    base, other = candidates
    costs = [c["cost_per_1000_requests_usd"] for c in candidates]
    cheaper = None if None in costs else (default if costs[0] <= costs[1] else challenger)
    block: dict[str, Any] = {
        "rule": (
            f"spec §6.4: default {default}; if {challenger}'s {split} {task} macro-F1 is at"
            f" least {default}'s minus {max_gap * 100:g} points, the cheaper of the two"
        ),
        "split": split,
        "task": task,
        "metric": "overall.macro_f1",
        "max_gap": max_gap,
        "default_model": default,
        "challenger": challenger,
        "candidates": candidates,
        "cheaper": cheaper,
        "decided_at": decided_at,
    }
    missing = [c["model"] for c in candidates if c["macro_f1"] is None]
    if missing:
        for model in missing:
            reason = "no dev run" if runs.get(model) is None else "n = 0 (no Labels)"
            notices.append(f"{model}: {reason} for {task} on {split}")
        return block | {
            "status": "pending",
            "selected": default,
            "gap": None,
            "within_gap": None,
            "reason": f"comparison pending ({', '.join(missing)} without a score);"
            f" the default {default} stands",
            "notices": notices,
        }
    gap = round(base["macro_f1"] - other["macro_f1"], 9)
    within = gap <= max_gap
    if within:
        if cheaper is None:
            selected, reason = default, f"within {max_gap * 100:g} points, but a price is missing"
        else:
            selected = cheaper
            reason = (
                f"{challenger} is within {max_gap * 100:g} points ({-gap * 100:+.1f});"
                f" {cheaper} is cheaper"
            )
    else:
        selected = default
        reason = (
            f"{challenger} is {gap * 100:.1f} points behind (more than"
            f" {max_gap * 100:g}); the default {default} stands"
        )
    if gap < -max_gap and selected == default:
        notices.append(
            f"{challenger} scores {-gap * 100:.1f} points higher than {default} but is"
            " dearer; the rule keeps the default (owner decision)"
        )
    shutdown = (shutdowns or {}).get(selected)
    if shutdown:
        notices.append(f"{selected} is deprecated and shuts down on {shutdown}")
    return block | {
        "status": "compared",
        "selected": selected,
        "gap": gap,
        "within_gap": within,
        "reason": reason,
        "notices": notices,
    }
