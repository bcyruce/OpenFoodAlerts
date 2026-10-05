from typer.testing import CliRunner

from openfoodalerts import __version__
from openfoodalerts.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_jobs_are_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "ingest-openfda" in result.output
    assert "parse" in result.output
    assert "replay" in result.output
