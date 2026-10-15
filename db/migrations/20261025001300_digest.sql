-- migrate:up

-- Digest deliveries are claimed before they are sent (spec §5 `send-digest`: at most one
-- per Subscription per day; re-runs after a crash never send twice). See
-- pipeline/src/openfoodalerts/mail/deliveries.py for the protocol:
--
-- 1. INSERT a row with status 'sending'; sent_at is the end of the window the Digest
--    covers, and digest_date (generated) its Europe/Amsterdam day. The unique index
--    below lets only one live claim per Subscription and day exist, so a second run (or
--    a concurrent one) skips the Subscription.
-- 2. Send through the provider.
-- 3. UPDATE the row to 'sent' with the provider's message id, or to 'failed' when the
--    provider certainly did not accept it; a failed claim no longer blocks the day, so the
--    next run retries.
--
-- A row left in 'sending' (crash or timeout between 1 and 3) blocks the day: we cannot
-- know whether the email went out, and sending it twice is the worse outcome. The next
-- Digest's window starts at the last 'sent' Digest, so that content is not lost.
--
-- Existing rows (confirmation emails) are 'sent'.

ALTER TABLE email_deliveries
    ADD COLUMN status text NOT NULL DEFAULT 'sent'
        CHECK (status IN ('sending', 'sent', 'failed')),
    ADD COLUMN digest_date date GENERATED ALWAYS AS (
        CASE WHEN kind = 'digest' THEN (sent_at AT TIME ZONE 'Europe/Amsterdam')::date END
    ) STORED;

CREATE UNIQUE INDEX email_deliveries_digest_day_uq
    ON email_deliveries (subscription_id, digest_date)
    WHERE kind = 'digest' AND status <> 'failed';

-- The mailer completes its own claims; it may change nothing else.
GRANT UPDATE (status, provider_message_id) ON email_deliveries TO ofa_mailer;

-- migrate:down
REVOKE UPDATE (status, provider_message_id) ON email_deliveries FROM ofa_mailer;
DROP INDEX email_deliveries_digest_day_uq;
ALTER TABLE email_deliveries DROP COLUMN digest_date, DROP COLUMN status;
