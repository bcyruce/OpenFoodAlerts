from typer.testing import CliRunner

from openfoodalerts.cli import app

runner = CliRunner()


def test_nvwa_jobs_are_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert "backfill-nvwa" in result.output
    assert "ingest-nvwa" in result.output
