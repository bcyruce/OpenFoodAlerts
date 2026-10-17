"""The README badge: a shields.io endpoint payload built from latest.json (ticket 25)."""

from typing import Any

import pytest

from openfoodalerts.eval.badge import badge_payload

LABEL = "T1 macro-F1 (test)"


def _report(*, labelled: int = 0, runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "synthetic": False,
        "label_status": {
            "dev": {"items": 100, "labelled": labelled},
            "test": {"items": 200, "labelled": labelled},
        },
        "runs": runs or [],
    }


def _run(
    model: str,
    macro_f1: float | None,
    ci: list[float] | None = None,
    *,
    kind: str = "model",
    split: str = "test",
    task: str = "hazard_category",
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": "v1",
        "kind": kind,
        "split": split,
        "task": task,
        "overall": {"n": 196, "macro_f1": macro_f1, "macro_f1_ci95": ci},
    }


def test_without_labels_the_badge_says_so() -> None:
    assert badge_payload(_report()) == {
        "schemaVersion": 1,
        "label": LABEL,
        "message": "no labels yet",
        "color": "lightgrey",
    }


def test_one_model_on_test_shows_its_overall_macro_f1_with_the_ci() -> None:
    report = _report(
        labelled=200,
        runs=[
            _run("baseline-keywords", 0.51, [0.4, 0.6], kind="baseline"),
            _run("claude-haiku-5-5", 0.6481, [0.5347, 0.7026], split="dev"),
            _run("claude-haiku-5-5", 0.7123, [0.6349, 0.7891]),
            _run("claude-haiku-5-5", 0.9, [0.8, 0.95], task="product_type"),
        ],
    )
    assert badge_payload(report) == {
        "schemaVersion": 1,
        "label": LABEL,
        "message": "claude-haiku-5-5 0.71 (95% CI 0.63\N{EN DASH}0.79)",
        "color": "blue",
    }


def test_several_models_are_all_shown_none_is_picked() -> None:
    report = _report(
        labelled=200,
        runs=[_run("claude-haiku-5-5", 0.7123, [0.6, 0.8]), _run("gpt-5-mini", 0.6949, [0.6, 0.8])],
    )
    assert (
        badge_payload(report)["message"] == "claude-haiku-5-5 0.71 \N{MIDDLE DOT} gpt-5-mini 0.69"
    )


def test_labels_but_no_model_run_on_test_is_not_a_number() -> None:
    report = _report(
        labelled=200,
        runs=[
            _run("baseline-keywords", 0.51, [0.4, 0.6], kind="baseline"),
            _run("claude-haiku-5-5", 0.65, [0.5, 0.7], split="dev"),
        ],
    )
    payload = badge_payload(report)
    assert payload["message"] == "no test run yet"
    assert payload["color"] == "lightgrey"


def test_a_synthetic_report_never_becomes_a_badge() -> None:
    with pytest.raises(ValueError, match="synthetic"):
        badge_payload(_report(labelled=200) | {"synthetic": True})
