"""Which Subscriptions may be emailed (spec §10, §11.1 #5).

The rule is the database view `sendable_subscriptions` (migration 20261025001110):
active, and the address is not on the do-not-send list. ofa_mailer can read nothing
else about Subscriptions, so the Digest and Instant email jobs (tickets 30, 31) select
recipients from here, and call `is_sendable` again right before each send so that an
unsubscribe or "delete my data" during a run stops the next email.
"""

from typing import Any

from openfoodalerts.db.connection import Connection

COLUMNS = "id, email, locale, filters, include_unclassified, instant_sources, confirmed_at"


def sendable_subscriptions(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        f"SELECT {COLUMNS} FROM sendable_subscriptions ORDER BY confirmed_at, id"
    ).fetchall()


def is_sendable(conn: Connection, subscription_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sendable_subscriptions WHERE id = %s", (subscription_id,)
    ).fetchone()
    return row is not None
