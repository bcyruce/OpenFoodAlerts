"""CLI of the harness: `ofa eval-run`, `ofa eval-refresh`, `ofa eval-example`."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.job import default_eval_dir

runner = CliRunner()


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    """A copy of the committed eval set with two invented Labels."""
    d = tmp_path / "eval"
    d.mkdir()
    for name in ("items.csv", "labels.csv", "silver.csv"):
        shutil.copy(default_eval_dir() / name, d / name)
    items = (d / "items.csv").read_text(encoding="utf-8").splitlines()[1:3]
    with (d / "labels.csv").open("a", encoding="utf-8", newline="") as f:
        for line in items:
            item_id = line.split(",", 1)[0]
            f.write(f"{item_id},A,v1,allergens,unsure,none,unknown,food,,2026-10-26T08:00:00Z\n")
    return d


def test_eval_commands_are_registered() -> None:
    output = runner.invoke(app, ["--help"]).output
    for command in ("eval-run", "eval-refresh", "eval-example"):
        assert command in output


def test_eval_run_without_a_database_writes_latest_json_and_says_so(
    eval_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://ofa:ofa@localhost:1/none?connect_timeout=2")
    out = eval_dir / "results" / "latest.json"
    result = runner.invoke(app, ["eval-run", "--eval-dir", str(eval_dir), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "eval_runs not written" in result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert {r["split"] for r in report["runs"]} == {"dev"}
    assert "baseline-keywords" in result.output
    assert "macro_f1" in result.output


@pytest.mark.db
def test_eval_run_stores_runs_and_labels_when_the_database_is_reachable(
    db: Connection, eval_dir: Path
) -> None:
    out = eval_dir / "latest.json"
    result = runner.invoke(app, ["eval-run", "--eval-dir", str(eval_dir), "--output", str(out)])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    n = db.execute("SELECT count(*) AS n FROM eval_runs").fetchone()
    assert n == {"n": len(report["runs"])}
    assert len(report["runs"]) >= 1


def test_eval_run_test_split_only_when_asked_and_rejects_other_splits(eval_dir: Path) -> None:
    out = eval_dir / "latest.json"
    args = ["eval-run", "--eval-dir", str(eval_dir), "--output", str(out), "--no-store"]
    assert runner.invoke(app, [*args, "--split", "test"]).exit_code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert all(r["split"] == "test" for r in report["runs"] + report["skipped"])
    assert runner.invoke(app, [*args, "--split", "all"]).exit_code == 2


def test_eval_refresh_fails_clearly_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["eval-refresh", "--split", "dev"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output
    unknown = runner.invoke(app, ["eval-refresh", "--model", "gpt-5-mini"])
    assert unknown.exit_code == 2 and "unknown classifier" in unknown.output


def test_eval_refresh_with_the_fake_model_writes_its_cache_and_eval_scores_it(
    eval_dir: Path,
) -> None:
    result = runner.invoke(app, ["eval-refresh", "--eval-dir", str(eval_dir), "--model", "fake"])
    assert result.exit_code == 0, result.output
    cache = eval_dir / "cache" / "fake" / "v1.jsonl"
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 100  # the dev split
    out = eval_dir / "latest.json"
    args = ["eval-run", "--eval-dir", str(eval_dir), "--output", str(out), "--no-store"]
    assert runner.invoke(app, args).exit_code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    [fake] = [r for r in report["runs"] if r["model"] == "fake"]
    assert fake["prompt_version"] == "v1" and fake["overall"]["n"] == 2


def test_eval_example_writes_a_synthetic_report(tmp_path: Path) -> None:
    out = tmp_path / "example.json"
    result = runner.invoke(app, ["eval-example", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["synthetic"] is True
