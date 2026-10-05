"""Postgres connections. The schema itself lives only in db/migrations (ADR 0001)."""

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgres://ofa:ofa@localhost:5432/ofa?sslmode=disable"

Connection = psycopg.Connection[dict[str, Any]]


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect(url: str | None = None) -> Connection:
    """Open a connection whose rows come back as dicts."""
    return psycopg.connect(url or database_url(), row_factory=dict_row)
