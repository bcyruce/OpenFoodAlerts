"""`ofa classify`: options, exit codes, the JSON job log."""

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from tests.mail_data import add_notification

pytestmark = pytest.mark.db
runner = CliRunner()
T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


def test_classify_is_registered() -> None:
    assert "classify" in runner.invoke(app, ["--help"]).output


def test_without_an_api_key_classify_stops_before_any_call(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    db.commit()
    result = runner.invoke(app, ["classify", "--limit", "20"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output
    assert db.execute("SELECT count(*) AS n FROM ai_classifications").fetchone() == {"n": 0}
    # a dry run needs no key
    dry = runner.invoke(app, ["classify", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "would call the model for 1" in dry.output


def test_the_fake_model_classifies_and_logs_the_run(db: Connection) -> None:
    add_notification(db, "openfda", "F-1", first_seen_at=T, hazard_text="Listeria")
    add_notification(db, "nvwa", "/a", first_seen_at=T, summary_source="Bevat glasdeeltjes.")
    db.commit()
    result = runner.invoke(app, ["classify", "--model", "fake", "--source", "openfda"])
    assert result.exit_code == 0, result.output
    assert "called the model for 1" in result.output
    log = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    [finished] = [e for e in log if e["event"] == "job_finished"]
    assert finished["job"] == "classify" and finished["status"] == "ok"
    assert (finished["model"], finished["prompt_version"], finished["classified"]) == (
        "fake",
        "v1",
        1,
    )
    assert finished["requests"] == 1 and "cache_read_input_tokens" in finished


@pytest.mark.parametrize(
    "args",
    [
        ["--source", "rasff"],
        ["--model", "gpt-5-mini"],
        ["--task", "summary"],
        ["--prompt-version", "v99"],
    ],
)
def test_bad_options_exit_2(db: Connection, args: list[str]) -> None:
    assert runner.invoke(app, ["classify", *args]).exit_code == 2
