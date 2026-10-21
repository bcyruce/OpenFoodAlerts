"""CLI of T6: `ofa classify --task summary_*` and `ofa factcheck-sample`."""

import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.factcheck import read_factcheck, write_factcheck
from openfoodalerts.eval.job import default_eval_dir
from tests.mail_data import add_notification

runner = CliRunner()
T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


@pytest.mark.db
def test_classify_writes_summaries_per_language(db: Connection) -> None:
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    add_notification(db, "nvwa", "/a", first_seen_at=T, summary_source="Bevat glasdeeltjes.")
    db.commit()
    zh = runner.invoke(app, ["classify", "--task", "summary_zh", "--model", "fake"])
    assert zh.exit_code == 0, zh.output
    assert "summary_zh fake v1: 1 in scope" in zh.output
    en = runner.invoke(app, ["classify", "--task", "summary_en", "--model", "fake"])
    assert "summary_en fake v1: 2 in scope" in en.output
    tasks = db.execute("SELECT task FROM ai_classifications ORDER BY task").fetchall()
    assert [r["task"] for r in tasks] == ["summary_en", "summary_en", "summary_zh"]
    bad = runner.invoke(app, ["classify", "--task", "summary_zh", "--source", "openfda"])
    assert bad.exit_code == 2


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    d = tmp_path / "eval"
    d.mkdir()
    for name in ("items.csv", "labels.csv", "silver.csv"):
        shutil.copy(default_eval_dir() / name, d / name)
    return d


def test_factcheck_sample_draws_50_summaries_and_keeps_judgments(eval_dir: Path) -> None:
    args = ["--eval-dir", str(eval_dir), "--model", "fake"]
    missing = runner.invoke(app, ["factcheck-sample", *args])
    assert missing.exit_code == 2 and "make eval-refresh" in missing.output
    assert runner.invoke(app, ["eval-refresh", *args]).exit_code == 0
    result = runner.invoke(app, ["factcheck-sample", *args])
    assert result.exit_code == 0, result.output
    path = eval_dir / "factcheck" / "t6.csv"
    rows = read_factcheck(path)
    assert len(rows) == 50 and {r.split for r in rows} == {"dev"}
    assert Counter(r.locale for r in rows).keys() == {"en", "nl", "zh"}
    assert "50 summaries" in result.output
    # a judgment survives sampling again
    write_factcheck(
        path, [rows[0].__class__(**{**rows[0].__dict__, "consistent": "no"}), *rows[1:]]
    )
    assert runner.invoke(app, ["factcheck-sample", *args]).exit_code == 0
    assert read_factcheck(path)[0].consistent == "no"
    # and `make eval` reports it
    out = eval_dir / "latest.json"
    run = runner.invoke(
        app, ["eval-run", "--eval-dir", str(eval_dir), "--output", str(out), "--no-store"]
    )
    assert run.exit_code == 0, run.output
    [block] = json.loads(out.read_text(encoding="utf-8"))["t6_factcheck"]["runs"]
    assert (block["n_checked"], block["n_consistent"], block["n_sampled"]) == (1, 0, 50)
    assert "t6 fact-check fake/v1 dev: 1 of 50 checked, 0 consistent" in run.output
