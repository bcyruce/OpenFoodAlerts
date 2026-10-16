-- Re-apply the do-not-send ledger after a restore (ticket 34; docs/privacy/ropa.md §2.6).
-- Used by ops/backup/restore.sh --ledger: psql reads the decrypted ledger CSV (written by
-- `backup.sh ledger`, hourly) from standard input. A restored dump can be up to a day older
-- than the ledger; without this step people who unsubscribed or deleted their data in that
-- window would get email again.
--
-- What it does, in one transaction:
--   * every suppressed address hash goes back on email_suppressions, and every Subscription
--     with that hash is deleted again (as "delete my data" did; deliveries cascade);
--   * every Subscription the ledger knows as unsubscribed is unsubscribed again, keeping the
--     original time so the 29-day cleanup still runs on schedule.
-- Re-running it is harmless.

CREATE TEMP TABLE ledger (
    kind            text NOT NULL CHECK (kind IN ('suppressed', 'unsubscribed')),
    email_hash      text,
    subscription_id uuid,
    at              timestamptz
);

\copy ledger FROM pstdin WITH (FORMAT csv, HEADER)

BEGIN;

INSERT INTO email_suppressions (email_hash, created_at)
SELECT email_hash, coalesce(at, now())
FROM ledger
WHERE kind = 'suppressed' AND email_hash IS NOT NULL
ON CONFLICT (email_hash) DO NOTHING;

DELETE FROM subscriptions s
USING ledger l
WHERE l.kind = 'suppressed' AND s.email_hash = l.email_hash;

UPDATE subscriptions s
SET status = 'unsubscribed',
    unsubscribed_at = coalesce(l.at, now()),
    confirm_token_hash = NULL,
    confirm_expires_at = NULL
FROM ledger l
WHERE l.kind = 'unsubscribed'
  AND s.id = l.subscription_id
  AND s.status <> 'unsubscribed';

SELECT kind, count(*) AS ledger_rows FROM ledger GROUP BY kind ORDER BY kind;

COMMIT;
