"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

import typer

from openfoodalerts import __version__

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


if __name__ == "__main__":  # pragma: no cover
    app()
