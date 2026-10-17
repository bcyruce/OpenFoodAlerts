-- migrate:up

-- Instant emails (spec §10.4, §5 `send-instant`): at most one per (Subscription,
-- Notification), also after a crash or with two runs at once. Same claim-then-send
-- protocol as the Digest (20261025001300; pipeline/src/openfoodalerts/mail/deliveries.py):
-- INSERT a 'sending' row and commit, send, then mark it 'sent' or 'failed'.
--
-- An Instant email is about exactly one Notification. Its id is copied into a generated
-- column (the caller cannot get it wrong) and a partial unique index allows one live
-- (sending or sent) Instant email per Subscription and Notification. A 'failed' row
-- (the provider certainly refused it) frees the pair for a retry; a row left 'sending'
-- keeps it: possibly sent, so never sent again.
--
-- No new table and no new privilege: ofa_mailer already inserts email_deliveries and may
-- only update status and provider_message_id. The daily cap of 5 per Subscription is
-- counted from these rows under a per-Subscription advisory lock (deliveries.py).

ALTER TABLE email_deliveries
    ADD CONSTRAINT email_deliveries_instant_one_notification
        CHECK (kind <> 'instant' OR cardinality(notification_ids) = 1),
    ADD COLUMN instant_notification_id bigint GENERATED ALWAYS AS (
        CASE WHEN kind = 'instant' THEN notification_ids[1] END
    ) STORED;

CREATE UNIQUE INDEX email_deliveries_instant_uq
    ON email_deliveries (subscription_id, instant_notification_id)
    WHERE kind = 'instant' AND status <> 'failed';

-- migrate:down
DROP INDEX email_deliveries_instant_uq;
ALTER TABLE email_deliveries
    DROP COLUMN instant_notification_id,
    DROP CONSTRAINT email_deliveries_instant_one_notification;
