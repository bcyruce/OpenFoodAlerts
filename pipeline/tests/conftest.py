"""Shared fixtures.

DB-backed tests use the database at TEST_DATABASE_URL, migrated with `make test-db`.
Before each test every table is truncated except migration bookkeeping and the tables
filled by migrations or seeds (listed in KEEP_TABLES); add new seed tables there.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from openfoodalerts.db.connection import Connection, connect

# Typer forces a rich terminal when GITHUB_ACTIONS is set, which puts ANSI codes inside
# option names in --help output. Read when typer's rich_utils is first imported, which
# happens after this module loads.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"

DEFAULT_TEST_DATABASE_URL = "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable"
FIXTURES = Path(__file__).parent / "fixtures"

KEEP_TABLES = {
    "schema_migrations",
    "sources",
    "countries",
    "hazard_categories",
    "product_categories",
}


def get_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Connection]:
    """A connection to a clean test database; DATABASE_URL points at it too."""
    url = get_test_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    conn = connect(url)
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    to_truncate = [r["tablename"] for r in rows if r["tablename"] not in KEEP_TABLES]
    if to_truncate:
        conn.execute(
            "TRUNCATE " + ", ".join(f'"{t}"' for t in to_truncate) + " RESTART IDENTITY CASCADE"
        )
    if any(r["tablename"] == "sources" for r in rows):
        conn.execute(
            "UPDATE sources SET last_success_at = NULL, last_error = NULL, last_error_at = NULL,"
            " contract_status = NULL, contract_checked_at = NULL, contract_error = NULL"
        )
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
