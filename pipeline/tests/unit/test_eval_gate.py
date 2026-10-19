"""The eval.yml regression gate (ticket 19): head's dev T1 macro-F1 against main's."""

from typing import Any

import pytest

from openfoodalerts.eval.gate import compare_reports, render_markdown


def _report(*runs: dict[str, Any], labelled: int = 100) -> dict[str, Any]:
    return {
        "synthetic": False,
        "label_status": {
            "dev": {"items": 100, "labelled": labelled},
            "test": {"items": 200, "labelled": 0},
        },
        "runs": list(runs),
        "skipped": [],
    }


def _run(
    model: str,
    macro_f1: float | None,
    *,
    prompt_version: str = "v1",
    kind: str = "model",
    split: str = "dev",
    task: str = "hazard_category",
    n: int = 100,
    ci: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": prompt_version,
        "kind": kind,
        "split": split,
        "task": task,
        "overall": {"n": n, "macro_f1": macro_f1, "macro_f1_ci95": ci},
    }


def test_a_drop_of_more_than_two_points_fails() -> None:
    result = compare_reports(
        _report(_run("claude-haiku-5-5", 0.70)),
        _report(_run("claude-haiku-5-5", 0.6799, prompt_version="v2")),
    )
    assert result.passed is False


def test_a_drop_of_exactly_two_points_passes() -> None:
    # 0.7002 - 0.6802 is 0.020000000000000018 in binary floating point: still "not more".
    result = compare_reports(
        _report(_run("claude-haiku-5-5", 0.7002)),
        _report(_run("claude-haiku-5-5", 0.6802, prompt_version="v2")),
    )
    assert result.passed is True


def test_only_model_runs_of_the_task_and_split_are_gated() -> None:
    base = _report(
        _run("claude-haiku-5-5", 0.70),
        _run("baseline-keywords", 0.60, kind="baseline", prompt_version="kw1"),
        _run("claude-haiku-5-5", 0.80, split="test"),
        _run("claude-haiku-5-5", 0.90, task="product_type"),
    )
    head = _report(
        _run("claude-haiku-5-5", 0.70),
        _run("baseline-keywords", 0.40, kind="baseline", prompt_version="kw1"),
        _run("claude-haiku-5-5", 0.50, split="test"),
        _run("claude-haiku-5-5", 0.50, task="product_type"),
    )
    result = compare_reports(base, head)
    assert result.passed is True
    assert [(r.model, r.gated) for r in result.rows] == [
        ("claude-haiku-5-5", True),
        ("baseline-keywords", False),
    ]


def test_each_side_uses_its_newest_prompt_version_of_the_model() -> None:
    # The PR adds v10; its checkout still holds the committed v9 cache, which make eval
    # scores too. The gate compares v10 (head) with main's newest, v9.
    base = _report(_run("claude-haiku-5-5", 0.70, prompt_version="v9"))
    head = _report(
        _run("claude-haiku-5-5", 0.70, prompt_version="v9"),
        _run("claude-haiku-5-5", 0.60, prompt_version="v10"),
    )
    result = compare_reports(base, head)
    assert result.passed is False
    (row,) = result.rows
    assert (row.base_prompt_version, row.head_prompt_version) == ("v9", "v10")
    assert row.drop == 0.1


def test_without_a_baseline_on_main_it_passes_with_a_notice() -> None:
    result = compare_reports(None, _report(_run("claude-haiku-5-5", 0.40)))
    assert result.passed is True
    assert result.rows[0].gated is False
    assert any("no baseline" in n for n in result.notices)


def test_without_dev_labels_it_passes_with_a_notice() -> None:
    # Today's committed state: no Labels, so every run is skipped and runs is empty.
    skipped = {
        "model": "claude-haiku-5-5",
        "prompt_version": "v1",
        "split": "dev",
        "task": "hazard_category",
        "reason": "no Labels",
    }
    empty = _report(labelled=0) | {"skipped": [skipped]}
    result = compare_reports(empty, empty)
    assert result.passed is True
    assert result.rows == ()
    assert any("no Labels" in n for n in result.notices)


def test_a_run_without_a_number_is_not_gated() -> None:
    # n = 0 (e.g. every Label unsure) makes macro_f1 null.
    result = compare_reports(
        _report(_run("claude-haiku-5-5", 0.70)),
        _report(_run("claude-haiku-5-5", None, n=0, prompt_version="v2")),
    )
    assert result.passed is True
    assert result.rows[0].gated is False
    assert any("claude-haiku-5-5" in n and "no macro-F1" in n for n in result.notices)


def test_with_several_models_each_one_on_both_sides_is_gated_on_its_own() -> None:
    base = _report(
        _run("claude-haiku-5-5", 0.70),
        _run("model-b", 0.70),
        _run("retired-model", 0.90),
    )
    head = _report(
        _run("claude-haiku-5-5", 0.75, prompt_version="v2"),
        _run("model-b", 0.65, prompt_version="v2"),
        _run("new-model", 0.10),
    )
    result = compare_reports(base, head)
    assert result.passed is False
    assert {r.model: (r.gated, r.regressed) for r in result.rows} == {
        "claude-haiku-5-5": (True, False),
        "model-b": (True, True),
        "new-model": (False, False),
        "retired-model": (False, False),
    }
    assert any("new-model" in n and "new" in n for n in result.notices)
    assert any("retired-model" in n and "not in this report" in n for n in result.notices)


def test_the_gate_uses_point_estimates_not_confidence_intervals() -> None:
    # The intervals overlap widely (dev has 100 items), but a 5-point drop still fails.
    result = compare_reports(
        _report(_run("claude-haiku-5-5", 0.70, ci=[0.60, 0.80])),
        _report(_run("claude-haiku-5-5", 0.65, ci=[0.55, 0.75], prompt_version="v2")),
    )
    assert result.passed is False


def test_a_synthetic_report_is_refused() -> None:
    with pytest.raises(ValueError, match="synthetic"):
        compare_reports(None, _report(_run("synthetic-model", 0.7)) | {"synthetic": True})


def test_the_markdown_summary_tables_both_sides() -> None:
    base = _report(
        _run("claude-haiku-5-5", 0.70, ci=[0.60, 0.80]),
        _run("baseline-keywords", 0.60, kind="baseline", prompt_version="kw1"),
    )
    head = _report(
        _run("claude-haiku-5-5", 0.65, ci=[0.55, 0.75], prompt_version="v2", n=98),
        _run("baseline-keywords", 0.6123, kind="baseline", prompt_version="kw1", n=98),
        _run("new-model", None, n=0),
    )
    # "~" stands for an en dash (ruff flags the literal character as ambiguous).
    assert render_markdown(compare_reports(base, head)) == (
        "### Eval gate: T1 `hazard_category` macro-F1 on dev\n"
        "\n"
        "**Failed**: claude-haiku-5-5 dropped more than 2.0 points below main.\n"
        "\n"
        "| Model | main | this PR | Change | 95% CI (PR) | n (main → PR) | Gate |\n"
        "|---|---|---|---|---|---|---|\n"
        "| claude-haiku-5-5 | 0.700 (v1) | 0.650 (v2) | -5.0 pt | 0.550~0.750 | 100 → 98"
        " | **regression** |\n"
        "| new-model | ~ | ~ (v1) | ~ | ~ | ~ → 0 | not gated |\n"
        "| baseline-keywords (baseline) | 0.600 (kw1) | 0.612 (kw1) | +1.2 pt | ~ | 100 → 98"
        " | not gated |\n"
        "\n"
        "The gate compares point estimates of model runs present on both sides (newest prompt"
        " version each); baselines and the intervals are for information.\n"
        "\n"
        "- new-model: new (not on main); not gated\n"
    ).replace("~", "\N{EN DASH}")


def test_an_improvement_passes() -> None:
    result = compare_reports(
        _report(_run("claude-haiku-5-5", 0.70)),
        _report(_run("claude-haiku-5-5", 0.75, prompt_version="v2")),
    )
    assert result.passed is True
