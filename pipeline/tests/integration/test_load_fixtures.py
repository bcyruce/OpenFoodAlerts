"""`ofa load-fixtures`: archive fixture snapshots and parse them (dev and CI data for the web)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.fixtures import load_fixtures

WEB_FIXTURES = Path(__file__).parents[3] / "web" / "e2e" / "fixtures"


def keys(db: Connection) -> dict[str, int]:
    rows = db.execute("SELECT source_key, current_version FROM notifications").fetchall()
    return {r["source_key"]: r["current_version"] for r in rows}


def test_loads_snapshots_in_order_and_versions_changed_records(
    db: Connection, fixtures_dir: Path
) -> None:
    load_fixtures(
        db,
        [
            fixtures_dir / "openfda" / "page_recent.json",
            WEB_FIXTURES / "openfda" / "later_snapshot.json",
        ],
    )
    loaded = keys(db)
    assert loaded["H-0015-2027"] == 2
    assert loaded["H-0016-2027"] == 1
    assert "Z-9001-2027" in loaded


def test_loading_twice_changes_nothing(db: Connection, fixtures_dir: Path) -> None:
    files = [
        fixtures_dir / "openfda" / "page_recent.json",
        WEB_FIXTURES / "openfda" / "later_snapshot.json",
    ]
    load_fixtures(db, files)
    raw_count = db.execute("SELECT count(*) AS n FROM raw_records").fetchone()
    load_fixtures(db, files)
    assert keys(db)["H-0015-2027"] == 2
    assert db.execute("SELECT count(*) AS n FROM raw_records").fetchone() == raw_count


def test_skips_files_without_results(db: Connection, fixtures_dir: Path) -> None:
    load_fixtures(db, [fixtures_dir / "openfda" / "not_found.json"])
    assert keys(db) == {}


def test_cli_loads_the_given_files(db: Connection, fixtures_dir: Path) -> None:
    result = CliRunner().invoke(app, ["load-fixtures", str(fixtures_dir / "openfda" / "pet.json")])
    assert result.exit_code == 0, result.output
    assert "2 records archived" in result.output
    assert set(keys(db)) == {"F-1753-2019", "F-1754-2019"}


def test_rejects_unsupported_sources(db: Connection, tmp_path: Path) -> None:
    (tmp_path / "xyz").mkdir()
    path = tmp_path / "xyz" / "x.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match=r"x\.json"):
        load_fixtures(db, [path])


def test_loads_rasff_and_nvwa_detail_snapshots(db: Connection, fixtures_dir: Path) -> None:
    # The Source is the nearest directory named after one (rasff/details/…, nvwa/detail/…).
    load_fixtures(
        db,
        [
            fixtures_dir / "rasff" / "details" / "881995.json",
            fixtures_dir / "nvwa" / "detail" / "cook-korianderzaad-update.html",
        ],
    )
    assert keys(db) == {
        "2026.9489": 1,
        "/actueel/nieuws/2026/10/13/veiligheidswaarschuwing-cook-korianderzaad-gemalen": 1,
    }
    hazards = db.execute("SELECT count(*) AS n FROM notification_hazards").fetchone()
    assert hazards is not None and hazards["n"] > 0
