"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

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


@app.command("send-digest")
def send_digest_cmd(
    day: Annotated[
        str | None,
        typer.Option(
            "--date",
            help="Amsterdam day (YYYY-MM-DD) to send for; default today. A past day covers"
            " the window up to the end of that day.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Build every Digest but send and record nothing.")
    ] = False,
) -> None:
    """Send the daily Digest to every sendable Subscription (spec §10.3); daily 07:00
    Europe/Amsterdam. At most one per Subscription per day; safe to re-run after a crash.

    Connects with MAILER_DATABASE_URL; sends through EMAIL_TRANSPORT (brevo, outbox, log).
    """
    from datetime import UTC, timedelta
    from datetime import datetime as dt
    from datetime import time as dtime

    from openfoodalerts.db.connection import mailer_database_url
    from openfoodalerts.mail.digest import DigestSettings, amsterdam_day, send_digest
    from openfoodalerts.mail.templates import AMSTERDAM
    from openfoodalerts.mail.transport import LogTransport, transport_from_env

    now = dt.now(UTC)
    if day is not None:
        try:
            chosen = dt.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            raise typer.BadParameter("use YYYY-MM-DD", param_hint="--date") from None
        if chosen > amsterdam_day(now):
            raise typer.BadParameter("cannot send a future day's Digest", param_hint="--date")
        end_of_day = dt.combine(chosen + timedelta(days=1), dtime(), AMSTERDAM)
        now = min(now, end_of_day - timedelta(microseconds=1))
    try:
        transport = LogTransport() if dry_run else transport_from_env()
        settings = DigestSettings.from_env()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    with connect(mailer_database_url()) as conn:
        result = send_digest(conn, transport, settings, now=now, dry_run=dry_run)
    if dry_run:
        for sid, new, updated, news in result.planned:
            typer.echo(f"{sid}: new {new}, updated {updated}, RASFF News {news}")
        typer.echo(f"{result.day}: would send {result.would_send}, nothing to send {result.empty}")
        return
    typer.echo(
        f"{result.day}: sent {result.sent}, nothing to send {result.empty},"
        f" already sent {result.already}, no longer sendable {result.unsendable},"
        f" failed {result.failed}, uncertain {result.uncertain}"
    )


@app.command("send-instant")
def send_instant_cmd(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Work out every Instant email but send and record nothing."),
    ] = False,
) -> None:
    """Send Instant emails (spec §10.4) for new high-priority Notifications; run after
    `classify`. At most once per (Subscription, Notification) and 5 per Subscription per
    day; safe to re-run after a crash.

    Connects with MAILER_DATABASE_URL; sends through EMAIL_TRANSPORT (brevo, outbox, log).
    """
    from datetime import UTC
    from datetime import datetime as dt

    from openfoodalerts.db.connection import mailer_database_url
    from openfoodalerts.mail.digest import DigestSettings
    from openfoodalerts.mail.instant import send_instant
    from openfoodalerts.mail.transport import LogTransport, transport_from_env

    try:
        transport = LogTransport() if dry_run else transport_from_env()
        settings = DigestSettings.from_env()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    with connect(mailer_database_url()) as conn:
        result = send_instant(conn, transport, settings, now=dt.now(UTC), dry_run=dry_run)
    if dry_run:
        for sid, nid in result.planned:
            typer.echo(f"{sid}: notification {nid}")
        typer.echo(f"would send {result.would_send}, over the daily cap {result.capped}")
        return
    typer.echo(
        f"sent {result.sent}, over the daily cap {result.capped}, already sent {result.already},"
        f" no longer sendable {result.unsendable}, failed {result.failed},"
        f" uncertain {result.uncertain}"
    )


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


TaxonomyOption = Annotated[
    Path | None,
    typer.Option(help="Taxonomy CSV (default: db/seed/taxonomy/v1.csv, else v1-draft.csv)."),
]
EvalDirOption = Annotated[
    Path | None, typer.Option(help="Directory of items.csv / labels.csv (default: eval/).")
]


def _print_sampling(summary: dict[str, object]) -> None:
    import json

    keys = ("taxonomy", "splits", "label_counts", "shortfall", "replacements")
    for key in keys:
        typer.echo(f"{key}: {json.dumps(summary[key], ensure_ascii=False)}")
    if summary.get("unknown_exclusions"):
        typer.echo(f"unknown exclusions: {summary['unknown_exclusions']}", err=True)


@app.command("eval-sample")
def eval_sample_cmd(
    taxonomy: TaxonomyOption = None,
    eval_dir: EvalDirOption = None,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 20261025,
    force: Annotated[
        bool, typer.Option(help="Write even if labelled items would leave the set.")
    ] = False,
) -> None:
    """Sample the 300-item eval set from the database and write eval/items.csv (spec §7.1).

    Reproducible: the same database contents, taxonomy and seed give identical files.
    Exclusions in eval/exclusions.csv are replayed. Exit code 3: labelled items would be
    dropped (nothing written).
    """
    from openfoodalerts.eval.job import EvalSetChanged, default_eval_dir, run_sampling
    from openfoodalerts.eval.labelset import default_taxonomy_path
    from openfoodalerts.eval.sampling import SamplingConfig

    with connect() as conn:
        try:
            _, summary = run_sampling(
                conn,
                taxonomy_path=taxonomy or default_taxonomy_path(),
                eval_dir=eval_dir or default_eval_dir(),
                config=SamplingConfig(seed=seed),
                force=force,
            )
        except EvalSetChanged as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(3) from exc
    _print_sampling(summary)


@app.command("eval-exclude")
def eval_exclude_cmd(
    item_ids: Annotated[list[str] | None, typer.Argument(help="Item ids to exclude.")] = None,
    from_labels: Annotated[
        bool, typer.Option(help="Also exclude every item labelled non-food in labels.csv.")
    ] = False,
    reason: Annotated[str, typer.Option(help="Recorded in exclusions.csv.")] = "non-food",
    taxonomy: TaxonomyOption = None,
    eval_dir: EvalDirOption = None,
    seed: Annotated[int, typer.Option(help="Sampling seed (as for eval-sample).")] = 20261025,
) -> None:
    """Remove items from the eval set and draw deterministic replacements.

    Each excluded item is replaced by the next ranked unused Notification of its stratum
    (else of its Source), with the same split and flags; eval/items.csv is rewritten.
    """
    from openfoodalerts.eval.job import default_eval_dir, exclude_items, non_food_items
    from openfoodalerts.eval.labelset import default_taxonomy_path
    from openfoodalerts.eval.sampling import SamplingConfig

    directory = eval_dir or default_eval_dir()
    ids = list(item_ids or []) + (non_food_items(directory) if from_labels else [])
    if not ids:
        typer.echo("nothing to exclude", err=True)
        raise typer.Exit(2)
    with connect() as conn:
        _, summary = exclude_items(
            conn,
            ids,
            reason=reason,
            taxonomy_path=taxonomy or default_taxonomy_path(),
            eval_dir=directory,
            config=SamplingConfig(seed=seed),
        )
    _print_sampling(summary)


@app.command("eval-silver")
def eval_silver_cmd(
    taxonomy: TaxonomyOption = None,
    eval_dir: EvalDirOption = None,
    size: Annotated[int, typer.Option(help="Notifications in the silver set.")] = 2000,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 20261025,
    since: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Only count from this date (default 2020-01-01)."),
    ] = None,
    stats_only: Annotated[bool, typer.Option(help="Print the statistics, write nothing.")] = False,
) -> None:
    """Sample the RASFF silver set (single-label Notifications) into eval/silver.csv.

    Prints the share of Notifications excluded because their Hazards span several T1 labels
    (for the data card). Eval-set RASFF items are left out.
    """
    from openfoodalerts.eval.files import read_items
    from openfoodalerts.eval.frame import FrameConfig
    from openfoodalerts.eval.job import default_eval_dir
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
    from openfoodalerts.eval.silver import build_silver, load_rasff_records, write_silver

    directory = eval_dir or default_eval_dir()
    items_path = directory / "items.csv"
    exclude = (
        {i.source_key for i in read_items(items_path) if i.source == "rasff"}
        if items_path.exists()
        else set()
    )
    tax = load_taxonomy(taxonomy or default_taxonomy_path())
    with connect() as conn:
        records = load_rasff_records(conn, FrameConfig(), start=since.date() if since else None)
    silver = build_silver(records, tax, size=size, seed=seed, exclude=exclude)
    s = silver.stats
    typer.echo(f"RASFF Notifications in range: {s.notifications}")
    typer.echo(f"  without any Hazard:          {s.no_hazards}")
    typer.echo(f"  with Hazards:                {s.with_hazards}")
    typer.echo(
        f"  several T1 labels (excluded): {s.multi_label} = {s.excluded_share:.1%} of those"
        " with Hazards"
    )
    typer.echo(f"  several RASFF categories:     {s.multi_category} = {s.multi_category_share:.1%}")
    typer.echo(f"  eligible (one label, not in eval set): {s.eligible}")
    typer.echo(f"silver set: {len(silver.rows)} of {size} wanted")
    for label in tax.labels:
        if label in silver.available:
            n = sum(1 for r in silver.rows if r.label == label)
            typer.echo(f"  {n:>5} / {silver.available[label]:>5}  {label}")
    if not stats_only:
        write_silver(directory / "silver.csv", silver.rows)


@app.command("eval-fetch-rasff")
def eval_fetch_rasff_cmd(
    taxonomy: TaxonomyOption = None,
    seed: Annotated[int, typer.Option(help="Sampling seed (as for eval-sample).")] = 20261025,
    max_requests: Annotated[
        int, typer.Option(help="Do nothing if the plan needs more requests than this.")
    ] = 150,
    dry_run: Annotated[bool, typer.Option(help="Print the plan only.")] = False,
) -> None:
    """Fetch the RASFF Notifications the eval sample needs for its rare labels.

    Only needed while the full RASFF backfill (ticket 08) is missing. Lists by Hazard
    category and fetches a few details per label (>= 3 s apart, archived like
    backfill-rasff). Then run `ofa parse --source rasff` and `ofa eval-sample`.
    Exit code 3: the plan exceeds --max-requests (nothing fetched).
    """
    from openfoodalerts.eval.frame import FrameConfig, load_frame
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
    from openfoodalerts.eval.rasff_fill import (
        DEFAULT_MARGIN,
        estimate_requests,
        fetch_plan,
        fill_rasff,
        rasff_demand,
    )
    from openfoodalerts.eval.sampling import SamplingConfig
    from openfoodalerts.sources.rasff.client import RasffClient

    tax = load_taxonomy(taxonomy or default_taxonomy_path())
    config = SamplingConfig(seed=seed)
    frame_config = FrameConfig()
    with connect() as conn:
        frame = load_frame(conn, tax, frame_config)
        demand = rasff_demand(frame, tax, config)
        plan = fetch_plan(frame, demand, margin=DEFAULT_MARGIN, seed=seed)
        requests = estimate_requests(plan)
        for label, n in sorted(plan.items(), key=lambda kv: -kv[1]):
            typer.echo(f"{n:>4}  {label}  (demand {demand[label]})")
        typer.echo(f"plan: {sum(plan.values())} details, at most {requests} requests")
        if dry_run or not plan:
            return
        if requests > max_requests:
            typer.echo(f"error: more than --max-requests {max_requests}", err=True)
            raise typer.Exit(3)
        with RasffClient.create() as client:
            result = fill_rasff(
                conn,
                client,
                plan,
                tax,
                seed=seed,
                since=frame_config.rasff_start,
                until=frame_config.end,
            )
    for label, n in result.fetched.items():
        typer.echo(f"{label}: fetched {n} of {plan[label]} ({result.available[label]} listed)")


SplitOption = Annotated[
    str, typer.Option(help="dev (default) or test; test only when explicitly asked for.")
]


def _check_split(split: str) -> None:
    if split not in ("dev", "test"):
        typer.echo(f"error: --split must be dev or test, not {split!r}", err=True)
        raise typer.Exit(2)


def _fmt(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, float) else "-" if value is None else str(value)


@app.command("eval-run")
def eval_run_cmd(
    split: SplitOption = "dev",
    taxonomy: TaxonomyOption = None,
    eval_dir: EvalDirOption = None,
    output: Annotated[
        Path | None, typer.Option(help="Report to write (default: eval/results/latest.json).")
    ] = None,
    store: Annotated[
        bool, typer.Option(help="Write eval_runs and mirror eval_labels if a database answers.")
    ] = True,
) -> None:
    """Score cached model outputs and the baselines on one split (`make eval`).

    Offline: no API calls, no network. Reads eval/items.csv, eval/labels.csv, eval/cache/
    and eval/silver.csv; writes eval/results/latest.json (runs of the other split are kept).
    With a reachable DATABASE_URL, also inserts one eval_runs row per run; without one it
    says so and still exits 0. Tasks without gold Labels are listed as skipped.
    """
    from datetime import UTC
    from datetime import datetime as dt

    from openfoodalerts.eval.harness import current_git_sha, run_eval
    from openfoodalerts.eval.job import REPO_ROOT, default_eval_dir
    from openfoodalerts.eval.labelset import default_taxonomy_path

    _check_split(split)
    directory = eval_dir or default_eval_dir()
    out = output or directory / "results" / "latest.json"
    report, notices = run_eval(
        directory,
        split=split,
        taxonomy_path=taxonomy or default_taxonomy_path(),
        output=out,
        created_at=dt.now(UTC).isoformat(timespec="seconds"),
        git_sha=current_git_sha(REPO_ROOT),
    )
    for notice in notices:
        typer.echo(f"notice: {notice}")
    status = report["label_status"].get(split, {})
    typer.echo(
        f"split {split}: {status.get('labelled', 0)} of {status.get('items', 0)} items labelled"
    )
    for run in (r for r in report["runs"] if r["split"] == split):
        o = run["overall"]
        if "macro_f1" in o:
            scores = f"accuracy {_fmt(o['accuracy'])}  macro_f1 {_fmt(o['macro_f1'])}"
        else:
            scores = f"exact {_fmt(o['exact_match'])}  normalized {_fmt(o['normalized_match'])}"
        typer.echo(
            f"{run['model']}/{run['prompt_version']}  {run['task']}  n={o['n']}  {scores}"
            f"  abstained {_fmt(o['abstention_rate'])}"
        )
    for s in (s for s in report["skipped"] if s["split"] == split):
        typer.echo(f"skipped {s['model']}/{s['prompt_version']} {s['task']}: {s['reason']}")
    agreement, audit = report["agreement"], report["noise_audit"]
    typer.echo(f"agreement: kappa {_fmt(agreement['cohens_kappa'])} (n={agreement['n']})")
    typer.echo(
        f"noise audit: {_fmt(audit['agreement_with_official'])} with official (n={audit['n']})"
    )
    for fc in report["t6_factcheck"]["runs"]:
        typer.echo(
            f"t6 fact-check {fc['model']}/{fc['prompt_version']} {fc['split']}:"
            f" {fc['n_checked']} of {fc['n_sampled']} checked, {fc['n_consistent']} consistent"
            f" (stale {fc['n_stale']})"
        )
    typer.echo(f"wrote {out}")
    _write_badge(out, report)
    if store:
        _store_eval(report, split, directory)


def _write_badge(report_path: Path, report: dict[str, Any]) -> None:
    from openfoodalerts.eval.badge import write_badge

    badge = report_path.parent / "badge.json"
    write_badge(badge, report)
    typer.echo(f"wrote {badge}")


@app.command("eval-badge")
def eval_badge_cmd(
    report: Annotated[
        Path | None, typer.Option(help="Report to read (default: eval/results/latest.json).")
    ] = None,
) -> None:
    """Rebuild the README badge (badge.json, shields.io endpoint) next to a report.

    `ofa eval-run` does this too. Exit code 2: the report is synthetic.
    """
    import json

    from openfoodalerts.eval.job import default_eval_dir

    path = report or default_eval_dir() / "results" / "latest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        _write_badge(path, data)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("eval-gate")
def eval_gate_cmd(
    base: Annotated[
        Path, typer.Option(help="main's latest.json; a missing file = no baseline (passes).")
    ],
    head: Annotated[Path, typer.Option(help="The PR's latest.json (after make eval).")],
    task: Annotated[str, typer.Option(help="Task to gate.")] = "hazard_category",
    split: SplitOption = "dev",
    max_drop: Annotated[
        float, typer.Option(help="Largest allowed drop in macro-F1 (0.02 = 2 points).")
    ] = 0.02,
    summary: Annotated[
        Path | None,
        typer.Option(help="Append the Markdown table here (e.g. $GITHUB_STEP_SUMMARY)."),
    ] = None,
) -> None:
    """Regression gate of eval.yml: fail when a model's macro-F1 drops more than max-drop.

    Compares, per model run on both sides (newest prompt version each), the overall
    point estimate; baselines and confidence intervals are shown, not gated. Prints the
    Markdown summary. Exit codes: 0 passed (also: no baseline, no Labels, n = 0),
    1 regression, 2 unreadable or synthetic report.
    """
    import json

    from openfoodalerts.eval.gate import compare_reports, render_markdown

    _check_split(split)

    def load(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            typer.echo(f"error: cannot read {path}: {exc}", err=True)
            raise typer.Exit(2) from exc

    base_report = load(base) if base.exists() else None
    try:
        result = compare_reports(base_report, load(head), task=task, split=split, max_drop=max_drop)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    markdown = render_markdown(result)
    typer.echo(markdown, nl=False)
    if summary is not None:
        with summary.open("a", encoding="utf-8", newline="\n") as file:
            file.write(markdown)
    if not result.passed:
        raise typer.Exit(1)


def _store_eval(report: dict[str, object], split: str, eval_dir: Path) -> None:
    import psycopg

    from openfoodalerts.eval.files import read_labels
    from openfoodalerts.eval.store import store_runs, sync_labels

    try:
        with connect() as conn:
            runs = store_runs(conn, report, split)
            labels = sync_labels(conn, read_labels(eval_dir / "labels.csv"))
    except psycopg.Error as exc:
        typer.echo(f"notice: eval_runs not written ({type(exc).__name__}: database not usable)")
        return
    typer.echo(f"eval_runs: {runs} rows written; eval_labels: {labels} Labels mirrored")


@app.command("eval-refresh")
def eval_refresh_cmd(
    split: SplitOption = "dev",
    eval_dir: EvalDirOption = None,
    model: Annotated[
        list[str] | None,
        typer.Option(help="Classifier(s) to run (default: claude-haiku-5-5; fake: no API)."),
    ] = None,
) -> None:
    """Call the classifiers on one split and refresh eval/cache/ (paid API).

    `make eval` afterwards scores the refreshed cache. Exit code 2: the model cannot run
    (ANTHROPIC_API_KEY not set, unknown --model) or no classifier is configured.
    """
    from openfoodalerts.classify.model import ClassifierUnavailable
    from openfoodalerts.classify.registry import DEFAULT_MODEL
    from openfoodalerts.eval.files import read_items
    from openfoodalerts.eval.job import default_eval_dir
    from openfoodalerts.eval.refresh import NoClassifierConfigured, refresh_cache

    _check_split(split)
    directory = eval_dir or default_eval_dir()
    try:
        written = refresh_cache(
            read_items(directory / "items.csv"),
            split=split,
            cache_dir=directory / "cache",
            models=model or [DEFAULT_MODEL],
        )
    except (NoClassifierConfigured, KeyError, ClassifierUnavailable) as exc:
        typer.echo(f"error: {exc.args[0]}", err=True)
        raise typer.Exit(2) from exc
    for path, n in written.items():
        typer.echo(f"{path}: {n} outputs")


@app.command("factcheck-sample")
def factcheck_sample_cmd(
    split: SplitOption = "dev",
    eval_dir: EvalDirOption = None,
    model: Annotated[str, typer.Option(help="Model whose cached summaries to sample.")] = (
        "claude-haiku-5-5"
    ),
    prompt_version: Annotated[
        str | None,
        typer.Option(help="Cache file eval/cache/{model}/{version}.jsonl (default: newest)."),
    ] = None,
    n: Annotated[int, typer.Option(min=1, help="Sample size (spec §7.2: 50).")] = 50,
) -> None:
    """Sample T6 summaries of eval items for the human fact-check (eval/factcheck/t6.csv).

    Reproducible (fixed seed, equal share per Source x language); judgments already in the
    file are kept. Judge them with `uv run --group eval streamlit run ../eval/factcheck_app.py`
    or in the CSV; `make eval` reports them. Offline: reads the cache, calls nothing.
    Exit code 2: no cached summaries (run `make eval-refresh` first).
    """
    from collections import Counter

    from openfoodalerts.classify.prompts import latest_version
    from openfoodalerts.eval.cache import cache_path, read_run
    from openfoodalerts.eval.factcheck import (
        FACTCHECK_FILE,
        merge_sample,
        read_factcheck,
        sample_factcheck,
        write_factcheck,
    )
    from openfoodalerts.eval.files import read_items
    from openfoodalerts.eval.job import default_eval_dir

    _check_split(split)
    directory = eval_dir or default_eval_dir()
    version = prompt_version or latest_version("summary_en")
    path = cache_path(directory / "cache", model, version)
    items = read_items(directory / "items.csv")
    outputs = read_run(path).outputs if path.exists() else []
    sample = sample_factcheck(items, outputs, model=model, prompt_version=version, split=split, n=n)
    if not sample:
        typer.echo(
            f"error: no cached T6 summaries of {model}/{version} on {split} in {path};"
            f" run `make eval-refresh SPLIT={split} MODEL={model}` first",
            err=True,
        )
        raise typer.Exit(2)
    target = directory / FACTCHECK_FILE
    rows = merge_sample(read_factcheck(target), sample)
    write_factcheck(target, rows)
    judged = sum(
        bool(r.consistent) for r in rows if (r.model, r.prompt_version) == (model, version)
    )
    strata = Counter(f"{r.source}/{r.locale}" for r in sample)
    typer.echo(
        f"{len(sample)} summaries of {model}/{version} on {split} sampled"
        f" ({', '.join(f'{k} {v}' for k, v in sorted(strata.items()))}); {judged} judged so far"
    )
    typer.echo(f"wrote {target}")


@app.command("classify")
def classify_cmd(
    task: Annotated[
        str,
        typer.Option(
            help="Task (spec §6.1): hazard_category, or summary_en / summary_nl / summary_zh (T6)."
        ),
    ] = "hazard_category",
    source: Annotated[
        list[str] | None, typer.Option(help="Only these Sources (nvwa, openfda; default both).")
    ] = None,
    limit: Annotated[
        int | None, typer.Option(min=1, help="At most this many Notifications get a result.")
    ] = None,
    model: Annotated[
        str, typer.Option(help="claude-haiku-5-5 (default) or fake (keyword rules, no API).")
    ] = "claude-haiku-5-5",
    prompt_version: Annotated[
        str | None, typer.Option(help="Prompt file prompts/{task}/vN.md (default: newest).")
    ] = None,
    taxonomy: TaxonomyOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Count what would be classified; call nothing.")
    ] = False,
) -> None:
    """AI classifications of NVWA and openFDA Notifications (food, feed, food contact
    material) into ai_classifications; T1 also writes the AI primary hazard.

    Idempotent: Notifications that already have a result for this model, prompt version
    and input are skipped, and an input that was classified before is copied, not sent
    again. Exit code 2: the model cannot run (ANTHROPIC_API_KEY not set) or bad options;
    1: the run stopped after repeated failed requests.
    """
    from openfoodalerts.classify.job import classify_notifications
    from openfoodalerts.classify.model import ClassifierUnavailable, ItemFailed
    from openfoodalerts.classify.prompts import PromptError, load_prompt
    from openfoodalerts.classify.registry import MODELS, make_classifier
    from openfoodalerts.classify.tasks import make_task
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
    from openfoodalerts.jobs import run_job

    labels = load_taxonomy(taxonomy or default_taxonomy_path())
    try:
        chosen = make_task(task, labels)
        prompt = load_prompt(task, prompt_version)
    except (ValueError, PromptError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    unknown = [s for s in source or () if s not in chosen.sources]
    if unknown or model not in MODELS:
        typer.echo(
            f"error: --source must be one of {', '.join(chosen.sources)} and --model one of"
            f" {', '.join(MODELS)}",
            err=True,
        )
        raise typer.Exit(2)
    with connect() as conn:
        try:
            with run_job(conn, "classify", None) as stats:
                try:
                    result = classify_notifications(
                        conn,
                        task=chosen,
                        prompt=prompt,
                        model=model,
                        make_classifier=lambda: make_classifier(model, labels),
                        sources=source,
                        limit=limit,
                        dry_run=dry_run,
                    )
                finally:
                    stats.extra = {"task": task, "model": model, "prompt_version": prompt.version}
                stats.new = 0 if dry_run else result.classified + result.reused
                stats.unchanged = result.done
                stats.errors.extend(result.errors)
                # model requests go in the job log's own `requests` field
                stats.requests = result.usage.requests
                stats.extra |= {k: v for k, v in result.as_log().items() if k != "requests"}
        except ClassifierUnavailable as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(2) from exc
        except ItemFailed as exc:
            typer.echo(f"error: stopped after repeated failures: {exc}", err=True)
            raise typer.Exit(1) from exc
    verb = "would call" if dry_run else "called"
    typer.echo(
        f"{task} {model} {prompt.version}: {result.candidates} in scope, {result.done} done;"
        f" {verb} the model for {result.to_call if dry_run else result.classified},"
        f" copied {result.reused} (same input), abstained {result.abstained},"
        f" failed {result.failed}; AI hazards written {result.hazards_written}"
        f" (no category: {result.unmapped})"
    )
    u = result.usage
    if u.requests:
        typer.echo(
            f"usage: {u.requests} requests, input {u.input_tokens}, output {u.output_tokens},"
            f" cache write {u.cache_creation_input_tokens}, cache read {u.cache_read_input_tokens}"
            " tokens"
        )


@app.command("eval-example")
def eval_example_cmd(
    eval_dir: EvalDirOption = None,
    taxonomy: TaxonomyOption = None,
    output: Annotated[Path | None, typer.Option(help="Default: eval/results/example.json.")] = None,
) -> None:
    """Write the synthetic example report (invented Labels and model; "synthetic": true).

    For building the /evaluation page before real Labels exist. Reproducible.
    """
    from openfoodalerts.eval.files import read_items
    from openfoodalerts.eval.harness import write_report
    from openfoodalerts.eval.job import default_eval_dir
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
    from openfoodalerts.eval.synthetic import example_report

    directory = eval_dir or default_eval_dir()
    out = output or directory / "results" / "example.json"
    report = example_report(
        read_items(directory / "items.csv"),
        load_taxonomy(taxonomy or default_taxonomy_path()),
        directory / "silver.csv",
    )
    write_report(out, report)
    typer.echo(f"wrote {out} ({len(report['runs'])} runs, synthetic)")


@app.command("review-stats")
def review_stats_cmd() -> None:
    """The human review queue per task (spec §6.5): current AI results, queued (abstained
    or below the task's threshold, unreviewed) and reviewed.

    Review them on the local page: cd pipeline && uv run --group eval streamlit run
    ../eval/review_app.py
    """
    from openfoodalerts.classify.review_queue import review_stats

    with connect() as conn:
        stats = review_stats(conn)
    if not stats:
        typer.echo("no AI classifications yet")
    for s in stats:
        typer.echo(
            f"{s.task}: {s.current} current, queued"
            f" {s.queued_abstained + s.queued_low_confidence} ({s.queued_abstained} abstained,"
            f" {s.queued_low_confidence} below {s.min_confidence}); reviewed"
            f" {s.approved + s.corrected} ({s.approved} approved, {s.corrected} corrected)"
        )


@app.command("review-threshold")
def review_threshold_cmd(
    task: Annotated[str, typer.Argument(help="Task name, e.g. hazard_category.")],
    min_confidence: Annotated[
        str | None,
        typer.Argument(
            help="low, medium or high: the lowest confidence accepted without review."
            " Omit to show the current setting."
        ),
    ] = None,
) -> None:
    """Show or set a task's "low confidence" threshold for the review queue (spec §6.3;
    ticket 21 picks it from the dev coverage-accuracy curve). Results below it are queued,
    abstains always are; the default, medium, queues confidence = low."""
    from openfoodalerts.classify.review_queue import (
        DEFAULT_MIN_CONFIDENCE,
        set_threshold,
        thresholds,
    )

    with connect() as conn:
        if min_confidence is not None:
            try:
                set_threshold(conn, task, min_confidence)
            except ValueError as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(2) from exc
        current = thresholds(conn).get(task)
    shown = f"{current}" if current else f"{DEFAULT_MIN_CONFIDENCE} (default)"
    typer.echo(f"{task}: min_confidence {shown}")


if __name__ == "__main__":  # pragma: no cover
    app()
