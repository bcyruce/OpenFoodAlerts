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

Instant emails (migration 20261025001400) follow the same protocol with `claim_instant`:
one live claim per (Subscription, Notification), and at most `daily_cap` live Instant
emails per Subscription and Amsterdam day. `sent_at` of an Instant row is the moment it
was claimed.

These functions do not commit; the caller owns the transaction.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from openfoodalerts.db.connection import Connection

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
InstantRefusal = Literal["already", "capped"]


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


def claim_instant(
    conn: Connection,
    subscription_id: str,
    notification_id: int,
    *,
    now: datetime,
    first_seen_at: datetime,
    daily_cap: int,
) -> int | InstantRefusal:
    """Claim the Instant email for one Notification; the delivery id, or why not.

    "already": a live (sending or sent) one exists, whenever it was.
    "capped": `daily_cap` live Instant emails already went out on `now`'s Amsterdam day,
    or on the day the Notification was first seen (so one capped late yesterday is not
    sent after midnight: it is in the Digest). The caller commits right after.

    A transaction-level advisory lock per Subscription makes count-then-insert safe
    against a concurrent run; the unique index makes the pair safe on its own.
    """
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('ofa:instant:' || %s, 0))",
        (subscription_id,),
    )
    live = conn.execute(
        "SELECT 1 FROM email_deliveries WHERE subscription_id = %s AND kind = 'instant'"
        " AND instant_notification_id = %s AND status <> 'failed'",
        (subscription_id, notification_id),
    ).fetchone()
    if live is not None:
        return "already"
    days = {now.astimezone(AMSTERDAM).date(), first_seen_at.astimezone(AMSTERDAM).date()}
    if instant_count(conn, subscription_id, days) >= daily_cap:
        return "capped"
    row = conn.execute(
        """
        INSERT INTO email_deliveries (subscription_id, kind, notification_ids, sent_at, status)
        VALUES (%s, 'instant', %s, %s, 'sending')
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (subscription_id, [notification_id], now),
    ).fetchone()
    return "already" if row is None else int(row["id"])


def instant_count(conn: Connection, subscription_id: str, days: Iterable[date]) -> int:
    """Live Instant emails of a Subscription on the busiest of these Amsterdam days."""
    row = conn.execute(
        """
        SELECT coalesce(max(n), 0) AS n FROM (
            SELECT count(*) AS n FROM email_deliveries
            WHERE subscription_id = %s AND kind = 'instant' AND status <> 'failed'
              AND (sent_at AT TIME ZONE 'Europe/Amsterdam')::date = ANY(%s)
            GROUP BY (sent_at AT TIME ZONE 'Europe/Amsterdam')::date
        ) per_day
        """,
        (subscription_id, sorted(set(days))),
    ).fetchone()
    return 0 if row is None else int(row["n"])


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
    return _listed(conn, subscription_id, "instant", notification_ids)


def in_digest(conn: Connection, subscription_id: str, notification_ids: Sequence[int]) -> set[int]:
    """Which of these Notifications a live Digest of the Subscription already listed."""
    return _listed(conn, subscription_id, "digest", notification_ids)


def _listed(
    conn: Connection, subscription_id: str, kind: str, notification_ids: Sequence[int]
) -> set[int]:
    """Notifications in a live (sending or sent) email of this kind, whenever it was."""
    if not notification_ids:
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT unnest(notification_ids) AS id FROM email_deliveries
        WHERE subscription_id = %s AND kind = %s AND status <> 'failed'
          AND notification_ids && %s::bigint[]
        """,
        (subscription_id, kind, list(notification_ids)),
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
