"""Postgres connections. The schema itself lives only in db/migrations (ADR 0001)."""

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgres://ofa:ofa@localhost:5432/ofa?sslmode=disable"

Connection = psycopg.Connection[dict[str, Any]]


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def mailer_database_url() -> str:
    """Connection for the subscription jobs, which run as ofa_mailer in production.

    MAILER_DATABASE_URL; falls back to DATABASE_URL (the owner role in local development).
    """
    return os.environ.get("MAILER_DATABASE_URL") or database_url()


def connect(url: str | None = None) -> Connection:
    """Open a connection whose rows come back as dicts."""
    return psycopg.connect(url or database_url(), row_factory=dict_row)
