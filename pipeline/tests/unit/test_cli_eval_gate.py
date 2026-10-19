"""`ofa eval-gate`: exit codes and the job summary (ticket 19)."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.eval.job import default_eval_dir

runner = CliRunner()


def _write(path: Path, *macro_f1: float) -> Path:
    report: dict[str, Any] = {
        "synthetic": False,
        "label_status": {"dev": {"items": 100, "labelled": 100}},
        "runs": [
            {
                "model": "claude-haiku-5-5",
                "prompt_version": f"v{i + 1}",
                "kind": "model",
                "split": "dev",
                "task": "hazard_category",
                "overall": {"n": 100, "macro_f1": f1, "macro_f1_ci95": [f1 - 0.1, f1 + 0.1]},
            }
            for i, f1 in enumerate(macro_f1)
        ],
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _gate(base: Path, head: Path, *extra: str) -> Any:
    return runner.invoke(app, ["eval-gate", "--base", str(base), "--head", str(head), *extra])


def test_a_regression_exits_1_and_appends_the_table_to_the_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    result = _gate(
        _write(tmp_path / "base.json", 0.70),
        _write(tmp_path / "head.json", 0.70, 0.60),
        "--summary",
        str(summary),
    )
    assert result.exit_code == 1
    assert "**Failed**: claude-haiku-5-5" in result.output
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n")
    assert "| claude-haiku-5-5 | 0.700 (v1) | 0.600 (v2) | -10.0 pt |" in text


def test_within_the_allowed_drop_exits_0(tmp_path: Path) -> None:
    result = _gate(_write(tmp_path / "base.json", 0.70), _write(tmp_path / "head.json", 0.69))
    assert result.exit_code == 0
    assert "**Passed**" in result.output


def test_max_drop_is_configurable(tmp_path: Path) -> None:
    base, head = _write(tmp_path / "base.json", 0.70), _write(tmp_path / "head.json", 0.69)
    assert _gate(base, head, "--max-drop", "0.005").exit_code == 1


def test_a_missing_baseline_file_passes_with_a_notice(tmp_path: Path) -> None:
    result = _gate(tmp_path / "absent.json", _write(tmp_path / "head.json", 0.30))
    assert result.exit_code == 0
    assert "no baseline" in result.output


def test_an_unreadable_head_report_exits_2(tmp_path: Path) -> None:
    head = tmp_path / "head.json"
    head.write_text("{not json", encoding="utf-8")
    result = _gate(_write(tmp_path / "base.json", 0.70), head)
    assert result.exit_code == 2
    assert "head.json" in result.output


def test_a_missing_head_report_exits_2(tmp_path: Path) -> None:
    result = _gate(_write(tmp_path / "base.json", 0.70), tmp_path / "absent.json")
    assert result.exit_code == 2


def test_an_unreadable_baseline_exits_2_rather_than_passing(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    base.write_text("", encoding="utf-8")
    assert _gate(base, _write(tmp_path / "head.json", 0.70)).exit_code == 2


def test_a_synthetic_report_exits_2() -> None:
    example = default_eval_dir() / "results" / "example.json"
    result = _gate(example, example)
    assert result.exit_code == 2
    assert "synthetic" in result.output


def test_the_committed_latest_json_against_itself_passes() -> None:
    latest = default_eval_dir() / "results" / "latest.json"
    result = _gate(latest, latest)
    assert result.exit_code == 0
