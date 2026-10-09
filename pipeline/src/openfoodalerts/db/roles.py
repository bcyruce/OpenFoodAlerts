"""Enable login for the application roles (spec §11.2).

The migrations create `ofa_pipeline`, `ofa_web` and `ofa_mailer` as NOLOGIN and grant
their privileges; passwords never appear in migrations. Each environment runs
`ofa role-login <role>` once with the password in `<ROLE>_PASSWORD` (e.g. OFA_WEB_PASSWORD).
Roles are cluster-wide, so this applies to every database on the server.
"""

from psycopg import sql

from openfoodalerts.db.connection import Connection

ROLES = ("ofa_pipeline", "ofa_web", "ofa_mailer")


def password_env(role: str) -> str:
    return f"{role.upper()}_PASSWORD"


def enable_login(conn: Connection, role: str, password: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    if not password:
        raise ValueError("empty password")
    conn.execute(
        sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )
    conn.commit()
