"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

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


if __name__ == "__main__":  # pragma: no cover
    app()
