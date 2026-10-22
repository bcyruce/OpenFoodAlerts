"""`ofa eval-threshold` writes the chosen threshold into review_settings (ticket 20)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.classify.review_queue import thresholds
from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection

pytestmark = pytest.mark.db
runner = CliRunner()


def test_the_chosen_threshold_is_set_for_the_review_queue(db: Connection, tmp_path: Path) -> None:
    curve = [
        {"min_confidence": "high", "coverage": 0.5, "accuracy": 0.97, "n": 50},
        {"min_confidence": "medium", "coverage": 0.8, "accuracy": 0.88, "n": 80},
        {"min_confidence": "low", "coverage": 1.0, "accuracy": 0.8, "n": 100},
    ]
    report = {
        "runs": [
            {
                "model": "claude-haiku-5-5",
                "prompt_version": "v1",
                "split": "dev",
                "task": "hazard_category",
                "kind": "model",
                "overall": {"n": 100, "macro_f1": 0.8, "coverage_accuracy": curve},
            }
        ]
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    result = runner.invoke(app, ["eval-threshold", "--report", str(path)])
    assert result.exit_code == 0, result.output
    assert thresholds(db) == {"hazard_category": "high"}
    assert "review_settings: hazard_category = high" in result.output
