-- migrate:up

-- Who may receive a Digest or Instant email (spec §10, §11.1 #5). The rule lives in the
-- database so the mailer jobs (tickets 30, 31) cannot forget it: ofa_mailer no longer
-- reads `subscriptions` or `email_suppressions` directly, only this view.
--
-- A Subscription is sendable when it is active (confirmed, not unsubscribed) and its
-- address is not on the do-not-send list. The suppression list holds HMACs keyed with
-- a pepper the database does not know, so every Subscription now stores the same HMAC
-- of its address (`email_hash`, written by the web). Rows without one (created before
-- this migration, local databases only) are not sendable: fail closed.

ALTER TABLE subscriptions
    ADD COLUMN email_hash text CHECK (email_hash ~ '^[0-9a-f]{64}$');
CREATE INDEX subscriptions_email_hash_idx ON subscriptions (email_hash);

CREATE VIEW sendable_subscriptions AS
SELECT s.id, s.email, s.locale, s.filters, s.include_unclassified, s.instant_sources,
       s.confirmed_at
FROM subscriptions s
WHERE s.status = 'active'
  AND s.email_hash IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM email_suppressions e WHERE e.email_hash = s.email_hash);

-- Default privileges hand every new relation to ofa_pipeline; this one is private.
REVOKE ALL ON sendable_subscriptions FROM ofa_pipeline;
REVOKE SELECT ON subscriptions, email_suppressions FROM ofa_mailer;
GRANT SELECT ON sendable_subscriptions TO ofa_mailer;

-- migrate:down
GRANT SELECT ON subscriptions, email_suppressions TO ofa_mailer;
DROP VIEW sendable_subscriptions;
DROP INDEX subscriptions_email_hash_idx;
ALTER TABLE subscriptions DROP COLUMN email_hash;
