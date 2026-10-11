"""`refresh-rasff`: re-fetch recent RASFF details to catch later changes (spec §5, daily).

RASFF keeps editing a Notification after validation (new distribution countries, measures,
a changed risk decision). For every known Notification whose `ecValidationDate`
(`published_at`) falls in the last 30 days the detail is fetched again; the archive keeps
it only when its content_hash changed. Turning a changed detail into a new version (and
flagging substantial ones) is the `parse` job's work.
"""

from datetime import UTC, datetime, timedelta

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, run_job
from openfoodalerts.sources.rasff.backfill import SOURCE, fetch_detail
from openfoodalerts.sources.rasff.client import RasffClient

WINDOW_DAYS = 30


def recent_notifications(conn: Connection, since: datetime) -> list[tuple[int, str]]:
    """(notifId, reference) of RASFF Notifications validated since `since`, newest first."""
    rows = conn.execute(
        """
        SELECT n.source_ref, n.source_key FROM notifications n
        JOIN sources s ON s.id = n.source_id
        WHERE s.code = %s AND n.published_at >= %s
        ORDER BY n.published_at DESC, n.source_key
        """,
        (SOURCE, since),
    ).fetchall()
    return [(int(r["source_ref"]), str(r["source_key"])) for r in rows]


def refresh_rasff(
    conn: Connection,
    client: RasffClient,
    *,
    now: datetime | None = None,
    max_details: int | None = None,
) -> JobStats:
    """Re-fetch the details of Notifications validated in the last 30 days.

    `now` defaults to the current time; `max_details` bounds a trial run (newest first).
    """
    since = (now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)
    with run_job(conn, "refresh-rasff", SOURCE, client.http) as stats:
        targets = recent_notifications(conn, since)
        stats.extra.update(since=since.isoformat(), due=len(targets), fetched=0, missing=0)
        for notif_id, reference in targets:
            if max_details is not None and stats.extra["fetched"] >= max_details:
                stats.extra["capped"] = True
                break
            stats.extra["fetched"] += 1
            fetch_detail(conn, client, notif_id, reference, stats)
    return stats
