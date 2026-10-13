"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

from datetime import datetime
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


@app.command("backfill-nvwa")
def backfill_nvwa_cmd() -> None:
    """List every NVWA safety warning (new list + archive) and fetch unarchived details.

    Resumable: details already in the archive are skipped.
    """
    from openfoodalerts.sources.nvwa.ingest import MIN_INTERVAL, backfill_nvwa

    with connect() as conn, PoliteClient(min_interval=MIN_INTERVAL) as client:
        backfill_nvwa(conn, client)


@app.command("ingest-nvwa")
def ingest_nvwa_cmd() -> None:
    """New NVWA warnings from API page 1, then refetch pages whose sitemap lastmod moved on."""
    from openfoodalerts.sources.nvwa.ingest import MIN_INTERVAL, ingest_nvwa

    with connect() as conn, PoliteClient(min_interval=MIN_INTERVAL) as client:
        ingest_nvwa(conn, client)


@app.command("ingest-rasff")
def ingest_rasff_cmd(
    max_details: Annotated[
        int | None, typer.Option(help="Stop after this many detail requests (trial runs).")
    ] = None,
    today: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Treat this date as today (default: Brussels)."),
    ] = None,
) -> None:
    """Fetch RASFF Notifications validated in the last 14 days whose detail is not archived.

    Run `ofa parse --source rasff` afterwards to turn them into Notifications.
    """
    from openfoodalerts.sources.rasff.client import RasffClient
    from openfoodalerts.sources.rasff.ingest import ingest_rasff

    with connect() as conn, RasffClient.create() as client:
        ingest_rasff(conn, client, today=today.date() if today else None, max_details=max_details)


@app.command("refresh-rasff")
def refresh_rasff_cmd(
    max_details: Annotated[
        int | None, typer.Option(help="Re-fetch at most this many details, newest first.")
    ] = None,
) -> None:
    """Re-fetch details of RASFF Notifications validated in the last 30 days.

    Changed details are archived; `ofa parse --source rasff` records them as new versions.
    """
    from openfoodalerts.sources.rasff.client import RasffClient
    from openfoodalerts.sources.rasff.refresh import refresh_rasff

    with connect() as conn, RasffClient.create() as client:
        refresh_rasff(conn, client, max_details=max_details)


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


@app.command("cleanup-subscriptions")
def cleanup_subscriptions_cmd() -> None:
    """Delete expired subscription data (spec §5): pending after 7 days, unsubscribed after
    30 days, email deliveries after 12 months. Connects with MAILER_DATABASE_URL.
    """
    from openfoodalerts.db.connection import mailer_database_url
    from openfoodalerts.subscriptions.cleanup import cleanup_subscriptions

    with connect(mailer_database_url()) as conn:
        counts = cleanup_subscriptions(conn)
    typer.echo(", ".join(f"{key}: {value}" for key, value in counts.items()))


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


@app.command("probe-contracts")
def probe_contracts_cmd(
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Only these Sources.")
    ] = None,
) -> None:
    """Check each Source's endpoints against the contract models (a few light requests).

    A Source whose contract failed is skipped by `parse` until a probe passes again; raw
    archiving continues. Exit code 0: all ok; 3: a Source failed or was unreachable.
    """
    from openfoodalerts.probe import EXIT_PROBLEMS, default_probes, probe_contracts
    from openfoodalerts.sources.nvwa.ingest import MIN_INTERVAL
    from openfoodalerts.sources.rasff.client import RasffClient

    with (
        connect() as conn,
        RasffClient.create() as rasff,
        PoliteClient(min_interval=MIN_INTERVAL) as nvwa,
        PoliteClient() as openfda,
    ):
        probes = default_probes(rasff, nvwa, openfda)
        unknown = set(source or ()) - set(probes)
        if unknown:
            typer.echo(f"error: unknown Source {', '.join(sorted(unknown))}", err=True)
            raise typer.Exit(2)
        results = probe_contracts(
            conn,
            {code: probes[code] for code in source} if source else probes,
            clients=(rasff, nvwa, openfda),
        )
    for result in results.values():
        typer.echo(f"{result.source:8} {result.status:12} {result.error or ''}".rstrip())
    if any(r.status != "ok" for r in results.values()):
        raise typer.Exit(EXIT_PROBLEMS)


@app.command("check-data")
def check_data_cmd() -> None:
    """Data quality assertions on the parsed Notifications (read-only).

    Exit code 0: every check holds (warnings allowed); 3: a check failed.
    """
    from openfoodalerts.quality import EXIT_FAILED, check_data, failed, format_report

    with connect() as conn:
        results = check_data(conn)
    typer.echo(format_report(results))
    if failed(results):
        raise typer.Exit(EXIT_FAILED)


@app.command("taxonomy-draft")
def taxonomy_draft_cmd(
    since: Annotated[str, typer.Option(help="Count Notifications from this date (YYYY-MM-DD).")] = (
        "2020-01-01"
    ),
    output: Annotated[Path, typer.Option(help="Draft CSV to write.")] = Path(
        "../db/seed/taxonomy/v1-draft.csv"
    ),
) -> None:
    """Count RASFF Notifications per Hazard category and write the draft T1 merge table.

    Read-only towards the database; ~30 list requests. The domain expert reviews the draft
    before it is frozen as taxonomy v1 (ticket 11).
    """
    from openfoodalerts.sources.rasff.client import RasffClient
    from openfoodalerts.taxonomy import count_hazard_categories, draft_merge, write_draft

    filter_since = datetime.strptime(since, "%Y-%m-%d").strftime("%d-%m-%Y 00:00:00")
    with RasffClient.create() as client:
        rows = draft_merge(count_hazard_categories(client, since=filter_since))
    write_draft(rows, output, since)
    for r in sorted(rows, key=lambda r: -r.count):
        typer.echo(f"{r.count:>6}  {r.name}  ->  {r.label}")


if __name__ == "__main__":  # pragma: no cover
    app()
