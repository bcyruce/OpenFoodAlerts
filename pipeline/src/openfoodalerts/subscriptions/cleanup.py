"""`ofa cleanup-subscriptions` (spec §5): delete subscription data past its retention period.

The rules live in the SQL function `cleanup_subscriptions()` (migration
20261025001100): pending Subscriptions 7 days after the last request, Subscriptions
30 days after unsubscribing (with their deliveries), and email_deliveries older than
12 months. Only ofa_mailer may execute it; no application role can DELETE from those
tables directly except the website ("delete my data").
"""

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import run_job


def cleanup_subscriptions(conn: Connection) -> dict[str, int]:
    """Run the retention cleanup once and return what it deleted, per kind."""
    with run_job(conn, "cleanup-subscriptions", None) as stats:
        row = conn.execute("SELECT * FROM cleanup_subscriptions()").fetchone()
        assert row is not None
        counts = {key: int(value) for key, value in row.items()}
        stats.extra.update(counts)
    return counts
