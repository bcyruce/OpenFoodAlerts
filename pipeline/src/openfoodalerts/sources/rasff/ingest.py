"""`ingest-rasff`: pick up newly published RASFF Notifications (spec §5, every 6 hours).

Walks every page of the list filtered to `ecValidDateFrom = today - 14 days` (the list is
not strictly date-ordered, so there is no early stop) and fetches the detail of each
Notification whose detail is not archived yet. Already archived Notifications are left to
`refresh-rasff`. The archive deduplicates by content_hash, so re-running is harmless.
Parsing is left to the `parse` job.
"""

from datetime import date, datetime, timedelta

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, run_job
from openfoodalerts.sources.rasff.backfill import SOURCE, walk_list
from openfoodalerts.sources.rasff.client import ITEMS_PER_PAGE, RasffClient
from openfoodalerts.sources.rasff.parser import RASFF_TZ

LOOKBACK_DAYS = 14


def rasff_today() -> date:
    """Today's date where RASFF validates notifications (Brussels)."""
    return datetime.now(RASFF_TZ).date()


def date_filter(since: date) -> dict[str, str]:
    """List filter on the validation date; the backend wants `dd-mm-yyyy 00:00:00`."""
    return {"ecValidDateFrom": since.strftime("%d-%m-%Y 00:00:00")}


def ingest_rasff(
    conn: Connection,
    client: RasffClient,
    *,
    today: date | None = None,
    max_details: int | None = None,
    items_per_page: int = ITEMS_PER_PAGE,
) -> JobStats:
    """Fetch the details of Notifications validated in the last 14 days and not yet archived.

    `today` defaults to the current Brussels date; `max_details` bounds a trial run.
    """
    since = (today or rasff_today()) - timedelta(days=LOOKBACK_DAYS)
    with run_job(conn, "ingest-rasff", SOURCE, client.http) as stats:
        stats.extra["since"] = since.isoformat()
        walk_list(
            conn,
            client,
            stats,
            filters=date_filter(since),
            max_details=max_details,
            items_per_page=items_per_page,
        )
    return stats
