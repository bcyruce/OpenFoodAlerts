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

DEFAULT_TEST_DATABASE_URL = "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable"
FIXTURES = Path(__file__).parent / "fixtures"

KEEP_TABLES = {"schema_migrations"}


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
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
