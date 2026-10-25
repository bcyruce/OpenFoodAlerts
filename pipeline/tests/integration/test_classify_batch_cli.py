"""`ofa classify --batch` and `ofa classify-batch-status` with the fake model's local Batch
stand-in (`classify.fake_batch`), against the test database."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from tests.mail_data import add_notification

pytestmark = pytest.mark.db
runner = CliRunner()
T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def batch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OFA_FAKE_BATCH_DIR", str(tmp_path / "batches"))
    return tmp_path / "batches"


def count(db: Connection, table: str) -> int:
    row = db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
    assert row is not None
    return int(row["n"])


def test_the_commands_are_registered() -> None:
    out = runner.invoke(app, ["--help"]).output
    assert "classify-batch-status" in out
    assert "--batch" in runner.invoke(app, ["classify", "--help"]).output


def test_a_dry_run_needs_no_key_and_estimates_the_batch(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    add_notification(db, "openfda", "F-2", first_seen_at=T, hazard_text="Salmonella")
    db.commit()
    result = runner.invoke(app, ["classify", "--batch", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would submit 2 requests in 1 batch" in result.output
    assert "estimated cost at Batch prices" in result.output
    assert count(db, "classify_batches") == 0
    # for real, without a key: exit 2 before anything is written
    real = runner.invoke(app, ["classify", "--batch"])
    assert real.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in real.output
    assert count(db, "classify_batches") == 0


def test_a_model_without_a_batch_api_is_refused_before_anything_is_written(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    db.commit()
    for extra in ([], ["--dry-run"]):
        result = runner.invoke(app, ["classify", "--batch", "--model", "deepseek-flash", *extra])
        assert result.exit_code == 2, result.output
        assert "deepseek-flash has no Batch API" in result.output
        assert "--concurrency" in result.output
    assert count(db, "classify_batches") == 0


def test_submit_then_status_stores_the_results(db: Connection) -> None:
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    add_notification(db, "nvwa", "/a", first_seen_at=T, summary_source="Bevat glasdeeltjes.")
    db.commit()
    submitted = runner.invoke(app, ["classify", "--batch", "--model", "fake"])
    assert submitted.exit_code == 0, submitted.output
    assert "submitted 2 requests in 1 batch" in submitted.output
    assert count(db, "ai_classifications") == 0
    log = [json.loads(line) for line in submitted.stderr.splitlines() if line.startswith("{")]
    [finished] = [e for e in log if e["event"] == "job_finished"]
    assert finished["job"] == "classify-batch" and finished["requests"] == 2
    status = runner.invoke(app, ["classify-batch-status"])
    assert status.exit_code == 0, status.output
    assert "stored 2" in status.output
    assert count(db, "ai_classifications") == 2
    # nothing open any more, nothing left to submit
    assert "no open batches" in runner.invoke(app, ["classify-batch-status"]).output
    again = runner.invoke(app, ["classify", "--batch", "--model", "fake"])
    assert "submitted 0 requests" in again.output


def test_a_batch_run_collects_open_batches_first(db: Connection) -> None:
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    db.commit()
    runner.invoke(app, ["classify", "--batch", "--model", "fake"])
    second = runner.invoke(app, ["classify", "--batch", "--model", "fake"])
    assert second.exit_code == 0, second.output
    assert "stored 1" in second.output
    assert count(db, "ai_classifications") == 1


def test_status_waits_until_every_batch_is_stored(db: Connection) -> None:
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    db.commit()
    runner.invoke(app, ["classify", "--batch", "--model", "fake"])
    result = runner.invoke(app, ["classify-batch-status", "--wait", "--interval", "0"])
    assert result.exit_code == 0, result.output
    assert count(db, "ai_classifications") == 1
