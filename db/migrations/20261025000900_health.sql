-- migrate:up
-- Contract status per Source, written by `ofa probe-contracts` (spec §3.4, §13):
--   ok          the light requests answered and matched the pydantic contract models;
--   failed      a response did not match (unexpected HTTP status, not JSON/HTML as
--               expected, missing or retyped fields): `parse` skips this Source until a
--               probe passes again, raw archiving continues;
--   unreachable network error or 5xx after retries: reported, but parse is not blocked.
-- NULL means never probed. contract_error is a short message written by the probe
-- (field paths and HTTP statuses, never URLs or response bodies); /api/health shows it.
ALTER TABLE sources
    ADD COLUMN contract_status     text CHECK (contract_status IN ('ok', 'failed', 'unreachable')),
    ADD COLUMN contract_checked_at timestamptz,
    ADD COLUMN contract_error      text;

-- RASFF silence detection (spec §13): newest first_seen_at per Source.
CREATE INDEX notifications_first_seen_idx ON notifications (source_id, first_seen_at DESC);

-- ofa_web already has SELECT on sources (table-level grant covers the new columns).

-- migrate:down
DROP INDEX notifications_first_seen_idx;
ALTER TABLE sources
    DROP COLUMN contract_error,
    DROP COLUMN contract_checked_at,
    DROP COLUMN contract_status;
