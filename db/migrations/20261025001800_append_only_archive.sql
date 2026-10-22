-- migrate:up
-- ADR 0004: the raw archive is append-only. The pipeline may read and insert raw records
-- but never change or remove them (spec §4.1); replay re-parses, it never rewrites.
REVOKE UPDATE, DELETE, TRUNCATE ON raw_records FROM ofa_pipeline;

-- migrate:down
GRANT UPDATE, DELETE ON raw_records TO ofa_pipeline;
