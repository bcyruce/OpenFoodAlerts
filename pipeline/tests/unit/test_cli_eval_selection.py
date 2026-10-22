"""`ofa eval-threshold` and `ofa eval-compare`: read latest.json, decide, write back."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app

runner = CliRunner()
HAIKU, GPT = "claude-haiku-5-5", "gpt-5-mini"


def curve(acc_high: float, acc_medium: float, acc_low: float) -> list[dict[str, Any]]:
    return [
        {"min_confidence": "high", "coverage": 0.5, "accuracy": acc_high, "n": 50},
        {"min_confidence": "medium", "coverage": 0.8, "accuracy": acc_medium, "n": 80},
        {"min_confidence": "low", "coverage": 0.95, "accuracy": acc_low, "n": 95},
    ]


def run(model: str, task: str = "hazard_category", macro_f1: float = 0.8) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": "v1",
        "split": "dev",
        "task": task,
        "kind": "model",
        "overall": {
            "n": 100,
            "macro_f1": macro_f1,
            "macro_f1_ci95": [macro_f1 - 0.1, macro_f1 + 0.1],
            "coverage_accuracy": curve(0.96, 0.91, 0.85),
        },
    }


def write(tmp_path: Path, report: dict[str, Any]) -> Path:
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_eval_threshold_writes_the_threshold_prints_the_curve_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, {"runs": [run(HAIKU), run(HAIKU, "product_category")], "x": 1})
    result = runner.invoke(
        app, ["eval-threshold", "--report", str(path), "--target-accuracy", "0.9", "--no-db"]
    )
    assert result.exit_code == 0, result.output
    assert "hazard_category" in result.output and "0.910" in result.output
    assert "<- chosen" in result.output
    report = read(path)
    assert report["x"] == 1
    assert [(t["task"], t["min_confidence"]) for t in report["thresholds"]] == [
        ("hazard_category", "medium"),
        ("product_category", "medium"),
    ]
    assert "product_type: no dev run" in result.output
    assert "review_settings not written (--no-db)" in result.output


def test_eval_threshold_without_labels_changes_nothing(tmp_path: Path) -> None:
    original = {
        "runs": [],
        "skipped": [{"model": HAIKU, "split": "dev", "task": "hazard_category"}],
    }
    path = write(tmp_path, original)
    result = runner.invoke(app, ["eval-threshold", "--report", str(path)])
    assert result.exit_code == 0, result.output
    assert "no threshold chosen" in result.output
    assert read(path) == original


def test_eval_threshold_refuses_the_test_split_and_a_synthetic_report(tmp_path: Path) -> None:
    path = write(tmp_path, {"runs": [run(HAIKU)]})
    refused = runner.invoke(app, ["eval-threshold", "--report", str(path), "--split", "test"])
    assert refused.exit_code == 2
    assert "dev" in refused.output
    synthetic = write(tmp_path, {"runs": [run(HAIKU)], "synthetic": True})
    assert runner.invoke(app, ["eval-threshold", "--report", str(synthetic)]).exit_code == 2


def test_eval_threshold_defaults_to_the_selected_model(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {"runs": [run(HAIKU), run(GPT)], "model_selection": {"selected": GPT}},
    )
    result = runner.invoke(app, ["eval-threshold", "--report", str(path), "--no-db"])
    assert result.exit_code == 0, result.output
    assert {t["model"] for t in read(path)["thresholds"]} == {GPT}


def test_eval_compare_writes_model_selection(tmp_path: Path) -> None:
    path = write(tmp_path, {"runs": [run(HAIKU, macro_f1=0.80), run(GPT, macro_f1=0.70)]})
    result = runner.invoke(
        app, ["eval-compare", "--report", str(path), "--cache-dir", str(tmp_path / "cache")]
    )
    assert result.exit_code == 0, result.output
    block = read(path)["model_selection"]
    assert (block["status"], block["selected"]) == ("compared", HAIKU)
    assert block["prices"]["verified_on"] == "2026-10-25"
    assert "selected: claude-haiku-5-5" in result.output
    assert "10.0 points behind" in result.output


def test_eval_compare_with_no_labels_records_a_pending_comparison(tmp_path: Path) -> None:
    path = write(tmp_path, {"runs": [], "skipped": []})
    result = runner.invoke(
        app, ["eval-compare", "--report", str(path), "--cache-dir", str(tmp_path / "cache")]
    )
    assert result.exit_code == 0, result.output
    block = read(path)["model_selection"]
    assert (block["status"], block["selected"]) == ("pending", HAIKU)
    assert "pending" in result.output


def test_eval_compare_uses_the_measured_usage(tmp_path: Path) -> None:
    from openfoodalerts.classify.model import Usage
    from openfoodalerts.eval.cache import write_usage

    cache = tmp_path / "cache"
    write_usage(
        cache, HAIKU, "dev", {"hazard_category": ("v1", Usage(10, 2000, 3000, 0, 40000))}, "t"
    )
    write_usage(cache, GPT, "dev", {"hazard_category": ("v1", Usage(10, 2000, 1000, 0, 0))}, "t")
    path = write(tmp_path, {"runs": [run(HAIKU, macro_f1=0.80), run(GPT, macro_f1=0.79)]})
    result = runner.invoke(app, ["eval-compare", "--report", str(path), "--cache-dir", str(cache)])
    assert result.exit_code == 0, result.output
    block = read(path)["model_selection"]
    assert {c["cost_basis"] for c in block["candidates"]} == {"measured"}
    # Haiku: (2000 x 0.10 + 3000 x 0.50 + 40000 x 0.01) / 1M / 10 = $0.00021 per request
    # GPT-5 mini: (2000 x 0.25 + 1000 x 2.00) / 1M / 10 = $0.00025 per request
    assert block["cheaper"] == HAIKU and block["selected"] == HAIKU


@pytest.mark.parametrize("command", ["eval-threshold", "eval-compare"])
def test_a_missing_report_is_an_error(tmp_path: Path, command: str) -> None:
    result = runner.invoke(app, [command, "--report", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
