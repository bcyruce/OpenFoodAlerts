"""Choosing the low-confidence threshold (spec §6.3) and the model (spec §6.4) from
latest.json; prices from eval/model_prices.json."""

from typing import Any

import pytest

from openfoodalerts.classify.model import Usage
from openfoodalerts.eval.prices import Rates, cost_usd, load_prices
from openfoodalerts.eval.selection import (
    ThresholdChoice,
    choose_threshold,
    merge_thresholds,
    select_model,
    threshold_entries,
)

HAIKU, DS = "claude-haiku-5-5", "deepseek-flash"


def points(*rows: tuple[str, float | None, float | None, int]) -> list[dict[str, Any]]:
    return [
        {"min_confidence": level, "coverage": cov, "accuracy": acc, "n": n}
        for level, cov, acc, n in rows
    ]


CURVE = points(("high", 0.5, 0.96, 50), ("medium", 0.8, 0.91, 80), ("low", 0.95, 0.85, 95))


def choose(curve: list[dict[str, Any]], **kw: Any) -> ThresholdChoice:
    choice = choose_threshold(curve, **kw)
    assert choice is not None
    return choice


def test_the_threshold_is_the_widest_coverage_that_keeps_the_target_accuracy() -> None:
    choice = choose(CURVE, target_accuracy=0.9)
    assert (choice.min_confidence, choice.met_target) == ("medium", True)
    assert (choice.coverage, choice.accuracy, choice.n) == (0.8, 0.91, 80)
    assert choose(CURVE, target_accuracy=0.85).min_confidence == "low"


def test_exactly_the_target_is_enough() -> None:
    curve = points(("high", 0.5, 0.95, 50), ("medium", 0.8, 0.9, 80), ("low", 1.0, 0.8, 100))
    assert choose(curve, target_accuracy=0.9).min_confidence == "medium"


def test_when_no_level_reaches_the_target_only_high_is_accepted_without_review() -> None:
    choice = choose(CURVE, target_accuracy=0.99)
    assert (choice.min_confidence, choice.met_target) == ("high", False)


def test_too_few_answers_at_a_level_do_not_count() -> None:
    curve = points(("high", 0.05, 1.0, 5), ("medium", 0.6, 0.8, 60), ("low", 0.9, 0.7, 90))
    choice = choose(curve, target_accuracy=0.9, min_n=10)
    assert (choice.min_confidence, choice.met_target) == ("high", False)


def test_an_empty_curve_chooses_nothing() -> None:
    empty = points(("high", None, None, 0), ("medium", None, None, 0), ("low", None, None, 0))
    assert choose_threshold(empty, target_accuracy=0.9) is None
    assert choose_threshold([], target_accuracy=0.9) is None


def run(
    model: str,
    task: str = "hazard_category",
    *,
    version: str = "v1",
    macro_f1: float | None = 0.8,
    n: int = 100,
    split: str = "dev",
    kind: str = "model",
    curve: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": version,
        "split": split,
        "task": task,
        "kind": kind,
        "overall": {
            "n": n,
            "macro_f1": macro_f1,
            "macro_f1_ci95": None if macro_f1 is None else [macro_f1 - 0.1, macro_f1 + 0.1],
            "coverage_accuracy": CURVE if curve is None else curve,
        },
    }


def test_threshold_entries_use_the_newest_prompt_of_the_model_on_dev() -> None:
    report = {
        "runs": [
            run(HAIKU, version="v1", curve=points(("high", 1.0, 0.5, 100))),
            run(HAIKU, version="v2"),
            run(HAIKU, version="v2", split="test", curve=points(("high", 1.0, 1.0, 100))),
            run(HAIKU, "product_category", version="v1"),
            run(DS, version="v3"),
            run("baseline-keywords", kind="baseline"),
        ]
    }
    entries, notices = threshold_entries(
        report,
        model=HAIKU,
        tasks=["hazard_category", "product_category", "product_type"],
        target_accuracy=0.9,
    )
    assert [(e["task"], e["prompt_version"], e["min_confidence"]) for e in entries] == [
        ("hazard_category", "v2", "medium"),
        ("product_category", "v1", "medium"),
    ]
    first = entries[0]
    assert first["model"] == HAIKU and first["split"] == "dev"
    assert (first["coverage"], first["accuracy"], first["n"]) == (0.8, 0.91, 80)
    assert first["target_accuracy"] == 0.9 and first["met_target"] is True
    assert notices == [f"product_type: no dev run of {HAIKU}"]


def test_no_labels_means_no_threshold_and_a_notice() -> None:
    report = {"runs": [], "skipped": [{"model": HAIKU, "split": "dev", "task": "hazard_category"}]}
    entries, notices = threshold_entries(
        report, model=HAIKU, tasks=["hazard_category"], target_accuracy=0.9
    )
    assert entries == []
    assert notices == [f"hazard_category: no dev run of {HAIKU}"]
    empty = points(("high", None, None, 0))
    entries, notices = threshold_entries(
        {"runs": [run(HAIKU, n=0, macro_f1=None, curve=empty)]},
        model=HAIKU,
        tasks=["hazard_category"],
        target_accuracy=0.9,
    )
    assert entries == []
    assert notices == [f"hazard_category: {HAIKU}/v1 has no answered dev items (n = 0)"]


def test_merging_replaces_the_same_model_prompt_and_task_only() -> None:
    old = [
        {
            "model": HAIKU,
            "prompt_version": "v1",
            "task": "hazard_category",
            "min_confidence": "low",
        },
        {"model": DS, "prompt_version": "v1", "task": "hazard_category", "min_confidence": "high"},
    ]
    new = [
        {
            "model": HAIKU,
            "prompt_version": "v1",
            "task": "hazard_category",
            "min_confidence": "medium",
        }
    ]
    assert merge_thresholds(old, new) == [old[1], new[0]]


PRICES = {
    HAIKU: Rates(input=0.10, cache_write=0.125, cache_read=0.01, output=0.50),
    # DeepSeek's peak price
    DS: Rates(input=0.30, cache_write=0.0, cache_read=0.006, output=1.20),
}
OFF_PEAK = {DS: Rates(input=0.15, cache_write=0.0, cache_read=0.003, output=0.60)}


def select(report: dict[str, Any], usage: dict[str, Usage] | None = None) -> dict[str, Any]:
    return select_model(report, prices=PRICES, usage=usage or {}, decided_at="2026-10-26")


def test_within_two_points_the_cheaper_model_is_chosen() -> None:
    report = {"runs": [run(HAIKU, macro_f1=0.80), run(DS, macro_f1=0.79)]}
    # measured: DeepSeek spends far fewer tokens per request here, so it is cheaper
    usage = {HAIKU: Usage(100, 20_000, 30_000, 0, 400_000), DS: Usage(100, 2_000, 1_000, 0, 0)}
    block = select(report, usage)
    assert block["status"] == "compared"
    assert block["selected"] == DS
    assert block["gap"] == pytest.approx(0.01)
    assert block["cheaper"] == DS
    [h, g] = block["candidates"]
    assert (h["model"], h["macro_f1"], h["cost_basis"]) == (HAIKU, 0.80, "measured")
    # (20k x 0.10 + 30k x 0.50 + 400k x 0.01) / 1M per 100 requests = 0.021
    assert h["cost_per_1000_requests_usd"] == pytest.approx(0.21)
    # (2k x 0.30 + 1k x 1.20) / 1M per 100 requests, at the peak price
    assert g["cost_per_1000_requests_usd"] == pytest.approx(0.018)


def test_a_model_priced_by_the_hour_is_compared_at_its_peak_price_with_a_notice() -> None:
    usage = {HAIKU: Usage(100, 2_000, 1_000, 0, 0), DS: Usage(100, 2_000, 1_000, 0, 0)}
    block = select_model(
        {"runs": [run(HAIKU, macro_f1=0.80), run(DS, macro_f1=0.80)]},
        prices=PRICES,
        usage=usage,
        decided_at="2026-10-26",
        off_peak=OFF_PEAK,
    )
    # Haiku (0.007 per 1,000) is cheaper than DeepSeek at peak (0.018), not off-peak (0.009)
    assert block["cheaper"] == HAIKU and block["selected"] == HAIKU
    [h, d] = block["candidates"]
    assert "cost_per_1000_requests_off_peak_usd" not in h
    assert d["cost_per_1000_requests_off_peak_usd"] == pytest.approx(0.009)
    assert any("deepseek-flash is compared at its peak price" in n for n in block["notices"])


def test_exactly_two_points_is_within() -> None:
    block = select({"runs": [run(HAIKU, macro_f1=0.70), run(DS, macro_f1=0.68)]})
    # nominal profile (no measured usage): Haiku is cheaper, so Haiku either way
    assert block["within_gap"] is True
    assert block["cheaper"] == HAIKU and block["selected"] == HAIKU
    assert all(c["cost_basis"] == "nominal" for c in block["candidates"])


def test_more_than_two_points_behind_keeps_the_default() -> None:
    usage = {HAIKU: Usage(1, 10_000, 10_000, 0, 0), DS: Usage(1, 1, 1, 0, 0)}
    block = select({"runs": [run(HAIKU, macro_f1=0.80), run(DS, macro_f1=0.77)]}, usage)
    assert (block["within_gap"], block["selected"]) == (False, HAIKU)
    assert "default" in block["reason"]


def test_a_much_better_but_dearer_challenger_is_flagged_not_chosen() -> None:
    block = select({"runs": [run(HAIKU, macro_f1=0.70), run(DS, macro_f1=0.80)]})
    assert block["selected"] == HAIKU
    assert any("10.0 points higher" in n for n in block["notices"])


def test_without_both_dev_runs_the_comparison_is_pending_and_the_default_stands() -> None:
    for report in (
        {"runs": [], "skipped": [{"model": HAIKU, "split": "dev", "task": "hazard_category"}]},
        {"runs": [run(HAIKU)]},
        {"runs": [run(HAIKU), run(DS, macro_f1=None, n=0)]},
        {"runs": [run(HAIKU), run(DS, split="test")]},
    ):
        block = select(report)
        assert block["status"] == "pending", report
        assert block["selected"] == HAIKU
        assert block["notices"]


def test_the_shutdown_of_a_selected_model_is_a_notice() -> None:
    usage = {HAIKU: Usage(1, 10_000, 10_000, 0, 0), DS: Usage(1, 1, 1, 0, 0)}
    block = select_model(
        {"runs": [run(HAIKU, macro_f1=0.80), run(DS, macro_f1=0.80)]},
        prices=PRICES,
        usage=usage,
        decided_at="2026-10-26",
        shutdowns={DS: "2026-12-11"},
    )
    assert block["selected"] == DS
    assert any("2026-12-11" in n for n in block["notices"])


def test_cost_is_tokens_times_the_rates() -> None:
    rates = Rates(input=0.10, cache_write=0.125, cache_read=0.01, output=0.50)
    # 1M uncached input, 2M cache writes, 10M cache reads, 1M output
    assert cost_usd(Usage(5, 1_000_000, 1_000_000, 2_000_000, 10_000_000), rates) == pytest.approx(
        0.10 + 0.25 + 0.10 + 0.50
    )


def test_the_committed_price_table_has_both_candidates_with_sources() -> None:
    table = load_prices()
    assert table.verified_on == "2026-10-25"
    haiku, ds, gpt = table.models[HAIKU], table.models[DS], table.models["gpt-5-mini"]
    assert haiku.standard == Rates(input=0.10, cache_write=0.125, cache_read=0.01, output=0.50)
    assert haiku.batch is not None
    assert haiku.batch.input == 0.05 and haiku.batch.output == 0.25
    assert haiku.off_peak is None
    # DeepSeek: standard is the peak price, half off-peak, no Batch API
    assert ds.standard == PRICES[DS]
    assert ds.off_peak == OFF_PEAK[DS]
    assert ds.batch is None and ds.shutdown is None
    # GPT-5 mini (the earlier challenger) stays priced until it shuts down
    assert gpt.standard == Rates(input=0.25, cache_write=0.0, cache_read=0.025, output=2.00)
    assert gpt.batch == Rates(input=0.125, cache_write=0.0, cache_read=0.0125, output=1.00)
    assert all(s.startswith("https://") for m in (haiku, ds, gpt) for s in m.sources)
    assert gpt.shutdown == "2026-12-11" and haiku.shutdown is None
