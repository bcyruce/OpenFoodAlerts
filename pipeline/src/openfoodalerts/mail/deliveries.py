"""email_deliveries bookkeeping for the mailer jobs (spec §4.1, §5, §10.5).

Claim, then send, then complete (migration 20261025001300):

1. `claim_digest` inserts a 'sending' row; the partial unique index allows one live
   Digest per Subscription and Europe/Amsterdam day, so a re-run or a concurrent run gets
   None and skips. The caller commits the claim *before* sending.
2. The caller sends.
3. `mark_sent` (with the provider id) or `mark_failed` (the provider certainly did not
   accept it; frees the day for the next run). Commit.

A crash or an uncertain error between 1 and 3 leaves 'sending': the day is used up and
nothing is sent twice (at most once). Such a Digest does not count as sent for the next
window (`last_sent_digest_at`), so if it never arrived its content comes again the next
day; if it did arrive, the next Digest repeats it. Repetition beats double sending and
beats losing content.

`sent_at` of a Digest row is the run's `as_of` (the end of the window it covers), so the
next window starts exactly where this one ended.

These functions do not commit; the caller owns the transaction.
"""

from collections.abc import Sequence
from datetime import date, datetime

from openfoodalerts.db.connection import Connection


def claim_digest(
    conn: Connection,
    subscription_id: str,
    as_of: datetime,
    notification_ids: Sequence[int],
) -> int | None:
    """Claim the Digest of `as_of`'s Amsterdam day (the generated digest_date) for a
    Subscription; None if one is already sent or in flight."""
    row = conn.execute(
        """
        INSERT INTO email_deliveries (subscription_id, kind, notification_ids, sent_at, status)
        VALUES (%s, 'digest', %s, %s, 'sending')
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (subscription_id, sorted(set(notification_ids)), as_of),
    ).fetchone()
    return None if row is None else int(row["id"])


def digest_claimed(conn: Connection, subscription_id: str, day: date) -> bool:
    """A live (sending or sent) Digest exists for that day: cheap pre-check before work."""
    row = conn.execute(
        "SELECT 1 FROM email_deliveries WHERE subscription_id = %s AND kind = 'digest'"
        " AND digest_date = %s AND status <> 'failed'",
        (subscription_id, day),
    ).fetchone()
    return row is not None


def mark_sent(conn: Connection, delivery_id: int, provider_message_id: str | None) -> None:
    conn.execute(
        "UPDATE email_deliveries SET status = 'sent', provider_message_id = %s WHERE id = %s",
        (provider_message_id, delivery_id),
    )


def mark_failed(conn: Connection, delivery_id: int) -> None:
    conn.execute("UPDATE email_deliveries SET status = 'failed' WHERE id = %s", (delivery_id,))


def last_sent_digest_at(conn: Connection, subscription_id: str) -> datetime | None:
    row = conn.execute(
        "SELECT max(sent_at) AS at FROM email_deliveries"
        " WHERE subscription_id = %s AND kind = 'digest' AND status = 'sent'",
        (subscription_id,),
    ).fetchone()
    return None if row is None else row["at"]


def sent_instantly(
    conn: Connection, subscription_id: str, notification_ids: Sequence[int]
) -> set[int]:
    """Which of these Notifications already went to the Subscription in an Instant email."""
    if not notification_ids:
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT unnest(notification_ids) AS id FROM email_deliveries
        WHERE subscription_id = %s AND kind = 'instant' AND status <> 'failed'
          AND notification_ids && %s::bigint[]
        """,
        (subscription_id, list(notification_ids)),
    ).fetchall()
    return {r["id"] for r in rows} & set(notification_ids)


def daily_volume(conn: Connection, day: date) -> dict[str, int]:
    """Emails handed to the provider on an Amsterdam day, per kind (spec §10.5).

    Counts 'sent' and 'sending' (possibly sent) rows; failed attempts never reached it.
    Confirmation emails count only when the website recorded them.
    """
    rows = conn.execute(
        """
        SELECT kind, count(*) AS n FROM email_deliveries
        WHERE status <> 'failed'
          AND sent_at >= (%s::date::timestamp AT TIME ZONE 'Europe/Amsterdam')
          AND sent_at < ((%s::date + 1)::timestamp AT TIME ZONE 'Europe/Amsterdam')
        GROUP BY kind ORDER BY kind
        """,
        (day, day),
    ).fetchall()
    return {r["kind"]: int(r["n"]) for r in rows}
