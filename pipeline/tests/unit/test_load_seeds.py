"""`ofa load-seeds` against the test database (needs `make test-db`)."""

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.db.seeds import load_seeds

pytestmark = pytest.mark.db

SEED_TABLES = ("countries", "hazard_categories", "product_categories")


def empty_seed_tables(db: Connection) -> None:
    """Inside the test's transaction only; the fixture rolls it back afterwards."""
    for table in SEED_TABLES:
        db.execute(f"DELETE FROM {table}")


def count(db: Connection, table: str) -> int:
    row = db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
    assert row is not None
    return int(row["n"])


def test_loads_every_seed_table(db: Connection) -> None:
    empty_seed_tables(db)
    counts = load_seeds(db)
    assert counts == {"countries": 256, "hazard_categories": 30, "product_categories": 37}
    for table, n in counts.items():
        assert count(db, table) == n


def test_loaded_rows_carry_rasff_ids_and_names(db: Connection) -> None:
    empty_seed_tables(db)
    load_seeds(db)
    nl = db.execute("SELECT * FROM countries WHERE iso2 = 'NL'").fetchone()
    assert nl is not None
    assert (nl["rasff_id"], nl["name_en"], nl["name_nl"], nl["name_zh"]) == (
        5026,
        "Netherlands",
        None,
        None,
    )
    hazard = db.execute("SELECT * FROM hazard_categories WHERE rasff_id = 21798").fetchone()
    assert hazard is not None
    assert hazard["name_en"] == "allergens"
    assert hazard["label"] is None
    assert hazard["taxonomy_version"] is None


def test_reloading_is_idempotent_and_keeps_local_columns(db: Connection) -> None:
    empty_seed_tables(db)
    load_seeds(db)
    db.execute("UPDATE countries SET name_nl = 'Nederland' WHERE iso2 = 'NL'")
    db.execute(
        "UPDATE hazard_categories SET label = 'allergens', taxonomy_version = 'v1', "
        "name_en = 'stale' WHERE rasff_id = 21798"
    )
    ids_before = db.execute("SELECT id, rasff_id FROM hazard_categories ORDER BY id").fetchall()

    assert load_seeds(db)["hazard_categories"] == 30

    assert count(db, "hazard_categories") == 30
    assert db.execute("SELECT id, rasff_id FROM hazard_categories ORDER BY id").fetchall() == (
        ids_before
    )
    hazard = db.execute("SELECT * FROM hazard_categories WHERE rasff_id = 21798").fetchone()
    assert hazard is not None
    assert (hazard["name_en"], hazard["label"], hazard["taxonomy_version"]) == (
        "allergens",
        "allergens",
        "v1",
    )
    nl = db.execute("SELECT name_nl FROM countries WHERE iso2 = 'NL'").fetchone()
    assert nl == {"name_nl": "Nederland"}


def test_cli_loads_and_commits(db: Connection) -> None:
    result = CliRunner().invoke(app, ["load-seeds"])
    assert result.exit_code == 0, result.output
    assert "hazard_categories: 30 rows upserted" in result.output
    db.rollback()
    assert count(db, "countries") == 256
