"""`ofa role-login`: enable login for a NOLOGIN role created by the migrations."""

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.db.roles import enable_login

# Roles are cluster-wide: use the local placeholder from .env.example, so running the tests
# does not break a local WEB_DATABASE_URL.
PASSWORD = "ofa_web_local"


def as_role(db: Connection, role: str, password: str) -> psycopg.Connection[tuple[object, ...]]:
    params = conninfo_to_dict(db.info.dsn)
    params.update(user=role, password=password)
    return psycopg.connect(make_conninfo(**params))  # type: ignore[arg-type]


def test_web_role_reads_public_tables_but_not_the_raw_archive(db: Connection) -> None:
    enable_login(db, "ofa_web", PASSWORD)
    with as_role(db, "ofa_web", PASSWORD) as web:
        assert web.execute("SELECT count(*) FROM notifications").fetchone() is not None
        assert web.execute("SELECT count(*) FROM notification_versions").fetchone() is not None
        assert web.execute("SELECT code FROM sources").fetchall()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            web.execute("SELECT count(*) FROM raw_records")


def test_web_role_cannot_write(db: Connection) -> None:
    enable_login(db, "ofa_web", PASSWORD)
    with (
        as_role(db, "ofa_web", PASSWORD) as web,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        web.execute("UPDATE sources SET last_error = 'x'")


def test_only_application_roles_can_be_enabled(db: Connection) -> None:
    with pytest.raises(ValueError, match="ofa"):
        enable_login(db, "postgres", "x")


def test_cli_reads_the_password_from_the_environment(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OFA_WEB_PASSWORD", PASSWORD)
    result = CliRunner().invoke(app, ["role-login", "ofa_web"])
    assert result.exit_code == 0, result.output
    with as_role(db, "ofa_web", PASSWORD) as web:
        assert web.execute("SELECT 1").fetchone() == (1,)


def test_cli_refuses_without_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFA_WEB_PASSWORD", raising=False)
    result = CliRunner().invoke(app, ["role-login", "ofa_web"])
    assert result.exit_code == 1
    assert "OFA_WEB_PASSWORD" in result.output
