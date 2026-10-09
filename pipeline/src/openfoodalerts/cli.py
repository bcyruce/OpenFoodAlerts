"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

from pathlib import Path
from typing import Annotated

import typer

from openfoodalerts import __version__
from openfoodalerts.db.connection import connect
from openfoodalerts.http import PoliteClient

app = typer.Typer(
    name="ofa",
    help="OpenFoodAlerts pipeline jobs. Each job is idempotent and safe to re-run.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """OpenFoodAlerts pipeline jobs."""


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)


@app.command("ingest-openfda")
def ingest_openfda_cmd() -> None:
    """Full sync of openFDA food enforcement when its snapshot (meta.last_updated) changed."""
    from openfoodalerts.sources.openfda.ingest import ingest_openfda

    with connect() as conn, PoliteClient() as client:
        ingest_openfda(conn, client)


@app.command("backfill-rasff")
def backfill_rasff_cmd(
    start_page: Annotated[int, typer.Option(help="First list page to read.")] = 1,
    max_pages: Annotated[int | None, typer.Option(help="Stop after this many list pages.")] = None,
    max_details: Annotated[
        int | None, typer.Option(help="Stop after this many detail requests.")
    ] = None,
) -> None:
    """Walk all RASFF list pages and fetch every detail not yet archived (resumable).

    Safe to stop with Ctrl-C at any moment; re-running continues where it stopped.
    """
    from openfoodalerts.sources.rasff.backfill import backfill_rasff
    from openfoodalerts.sources.rasff.client import RasffClient

    with connect() as conn, RasffClient.create() as client:
        try:
            backfill_rasff(
                conn, client, start_page=start_page, max_pages=max_pages, max_details=max_details
            )
        except KeyboardInterrupt:
            typer.echo("interrupted: archived details are kept; re-run to resume.", err=True)
            raise typer.Exit(130) from None


@app.command("parse")
def parse_cmd(
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Only these Sources.")
    ] = None,
) -> None:
    """Parse archived raw records into Notifications (idempotent)."""
    from openfoodalerts.parse.run import parse

    with connect() as conn:
        parse(conn, source)


@app.command("replay")
def replay_cmd(
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Only these Sources.")
    ] = None,
) -> None:
    """Rebuild Notifications and versions from the raw archive with the current parsers.

    Makes no network requests; running it twice gives the same result (ADR 0004).
    """
    from openfoodalerts.parse.run import replay

    with connect() as conn:
        replay(conn, source)


@app.command("seed-rasff-lookups")
def seed_rasff_lookups() -> None:
    """Diff the live RASFF dictionaries against db/seed/rasff/. Read-only.

    Exit code 0: identical; 3: differences found (report printed); 1: fetch failed.
    """
    from openfoodalerts.sources.rasff import lookups

    try:
        with lookups.make_client() as client:
            diffs = lookups.check_against_seed(client)
    except lookups.RasffLookupFetchError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(lookups.format_report(diffs))
    if any(d.has_changes for d in diffs):
        raise typer.Exit(lookups.EXIT_DIFFERENCES)


@app.command("export-rasff-lookups")
def export_rasff_lookups() -> None:
    """Overwrite db/seed/rasff/ with the live RASFF dictionaries (no DB access).

    Run only after reviewing `ofa seed-rasff-lookups`; commit the resulting diff.
    """
    from openfoodalerts.sources.rasff import lookups

    with lookups.make_client() as client:
        counts = lookups.export_seeds(client)
    for dictionary, count in counts.items():
        typer.echo(f"{dictionary}: {count} entries")


@app.command("load-seeds")
def load_seeds() -> None:
    """Upsert the seed files in db/seed/ into DATABASE_URL (idempotent)."""
    from openfoodalerts.db import seeds
    from openfoodalerts.db.connection import connect

    with connect() as conn:
        counts = seeds.load_seeds(conn)
    for table, count in counts.items():
        typer.echo(f"{table}: {count} rows upserted")


@app.command("load-fixtures")
def load_fixtures_cmd(
    files: Annotated[
        list[Path],
        typer.Argument(help="Saved Source responses; the parent directory names the Source."),
    ],
) -> None:
    """Archive fixture snapshots in the given order and parse them. Dev/CI data only."""
    from openfoodalerts.fixtures import load_fixtures

    with connect() as conn:
        archived = load_fixtures(conn, files)
    typer.echo(f"{archived} records archived from {len(files)} files")


@app.command("role-login")
def role_login_cmd(
    role: Annotated[str, typer.Argument(help="ofa_pipeline, ofa_web or ofa_mailer.")],
) -> None:
    """Let an application role log in, with the password from <ROLE>_PASSWORD."""
    import os

    from openfoodalerts.db import roles

    password = os.environ.get(roles.password_env(role), "")
    if not password:
        typer.echo(f"error: set {roles.password_env(role)}", err=True)
        raise typer.Exit(1)
    with connect() as conn:
        roles.enable_login(conn, role, password)
    typer.echo(f"{role}: login enabled")


if __name__ == "__main__":  # pragma: no cover
    app()
