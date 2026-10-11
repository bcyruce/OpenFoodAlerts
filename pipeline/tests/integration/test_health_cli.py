"""CLI wiring of `check-data` and `probe-contracts` (exit codes, no network)."""

import pytest
from typer.testing import CliRunner

from openfoodalerts import probe
from openfoodalerts.cli import app
from openfoodalerts.contracts import ContractViolation
from openfoodalerts.db.connection import Connection

runner = CliRunner()


def test_health_jobs_are_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "probe-contracts" in result.output
    assert "check-data" in result.output


def test_check_data_passes_on_an_empty_database(db: Connection) -> None:
    result = runner.invoke(app, ["check-data"])
    assert result.exit_code == 0, result.output
    assert "PASS  published_at" in result.output


def test_check_data_exits_3_when_a_check_fails(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openfoodalerts import quality

    def broken(conn: Connection) -> quality.CheckResult:
        return quality.CheckResult("published_at", False, "1 displayed Notification without")

    monkeypatch.setattr(quality, "check_published_at", broken)
    result = runner.invoke(app, ["check-data"])
    assert result.exit_code == 3
    assert "FAIL  published_at" in result.output


def test_probe_contracts_rejects_an_unknown_source(db: Connection) -> None:
    result = runner.invoke(app, ["probe-contracts", "--source", "fsa"])
    assert result.exit_code == 2
    assert "unknown Source fsa" in result.output


def test_probe_contracts_prints_each_source_and_exits_3_on_a_failure(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise ContractViolation("list: HTTP 410")

    monkeypatch.setattr(
        probe,
        "default_probes",
        lambda *clients: {"rasff": lambda: None, "nvwa": broken, "openfda": lambda: None},
    )
    result = runner.invoke(app, ["probe-contracts", "-s", "rasff", "-s", "nvwa"])
    assert result.exit_code == 3
    assert result.stdout.splitlines() == ["rasff    ok", "nvwa     failed       list: HTTP 410"]
