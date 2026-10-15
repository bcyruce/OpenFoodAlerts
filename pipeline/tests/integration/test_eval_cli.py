"""CLI wiring of the eval commands (fixtures of all three Sources; no network)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.files import read_exclusions, read_items
from openfoodalerts.fixtures import load_fixtures

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).parents[1] / "fixtures"
runner = CliRunner()


@pytest.fixture
def loaded(db: Connection) -> Connection:
    files = [f for f in sorted((FIXTURES / "openfda").glob("*.json")) if f.name != "not_found.json"]
    files += sorted((FIXTURES / "rasff" / "details").glob("*.json"))
    files += sorted((FIXTURES / "nvwa" / "detail").glob("*.html"))
    load_fixtures(db, files)
    return db


def test_the_eval_commands_are_registered() -> None:
    output = runner.invoke(app, ["--help"]).output
    for command in ("eval-sample", "eval-exclude", "eval-silver", "eval-fetch-rasff"):
        assert command in output


def test_sample_exclude_from_labels_and_the_labelled_item_guard(
    loaded: Connection, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["eval-sample", "--eval-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "shortfall" in result.output
    items = read_items(tmp_path / "items.csv")
    assert items  # the fixtures fill fewer than 300

    assert runner.invoke(app, ["eval-exclude", "--eval-dir", str(tmp_path)]).exit_code == 2

    first = items[0]
    with (tmp_path / "labels.csv").open("a", encoding="utf-8", newline="") as f:
        f.write(
            f"{first.item_id},A,v1,allergens,,none,unknown,non-food,,2026-10-26T08:00:00+00:00\n"
        )
    result = runner.invoke(app, ["eval-exclude", "--from-labels", "--eval-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert [e.item_id for e in read_exclusions(tmp_path / "exclusions.csv")] == [first.item_id]

    # a labelled item that the new sample would not contain: refused, files untouched
    with (tmp_path / "labels.csv").open("a", encoding="utf-8", newline="") as f:
        f.write("nv-deadbeef,A,v1,allergens,,none,unknown,food,,2026-10-26T08:01:00+00:00\n")
    before = (tmp_path / "items.csv").read_bytes()
    result = runner.invoke(app, ["eval-sample", "--eval-dir", str(tmp_path)])
    assert result.exit_code == 3
    assert "nv-deadbeef" in result.output
    assert (tmp_path / "items.csv").read_bytes() == before
    forced = runner.invoke(app, ["eval-sample", "--eval-dir", str(tmp_path), "--force"])
    assert forced.exit_code == 0, forced.output


def test_silver_and_fetch_plan(loaded: Connection, tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval-silver", "--eval-dir", str(tmp_path), "--size", "5"])
    assert result.exit_code == 0, result.output
    assert "several T1 labels (excluded)" in result.output
    lines = (tmp_path / "silver.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "source_key,published_on,label,rasff_categories,subject"
    assert len(lines) == 1 + 5

    stats = runner.invoke(app, ["eval-silver", "--eval-dir", str(tmp_path / "x"), "--stats-only"])
    assert stats.exit_code == 0
    assert not (tmp_path / "x").exists()

    plan = runner.invoke(app, ["eval-fetch-rasff", "--dry-run"])
    assert plan.exit_code == 0, plan.output
    assert "plan:" in plan.output
    over = runner.invoke(app, ["eval-fetch-rasff", "--max-requests", "0"])
    assert over.exit_code == 3
