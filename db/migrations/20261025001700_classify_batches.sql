-- migrate:up

-- Batch backfill of AI classifications (spec §6.3 "回填分类走 Batch API", ticket 21).
-- Bookkeeping of `ofa classify --batch` so that a backfill survives interruption: which
-- provider batches were submitted, and which request (custom_id) stands for which input
-- (input_hash) of which Notifications. Results are stored through the same path as the
-- synchronous `ofa classify` (ai_classifications + derived rows). Pipeline / owner only:
-- not granted to ofa_web or ofa_mailer (ofa_pipeline gets its rights from the default
-- privileges of 20261025000350_roles.sql).

CREATE TABLE classify_batches (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider text NOT NULL CHECK (provider IN ('anthropic', 'openai', 'fake')),
    -- the provider's id; NULL until the provider confirmed the submission
    provider_batch_id text UNIQUE,
    task text NOT NULL CHECK (task ~ '^[a-z][a-z0-9_]*$'),
    model text NOT NULL,
    prompt_version text NOT NULL,
    -- preparing: rows written, not yet confirmed by the provider; submitted: waiting for
    -- the provider; ended: the provider finished, results not yet stored; stored: every
    -- result handled (failed requests are retried by the next submission); failed: the
    -- submission or the whole batch failed (its inputs are submitted again next time)
    status text NOT NULL DEFAULT 'preparing'
        CHECK (status IN ('preparing', 'submitted', 'ended', 'stored', 'failed')),
    request_count integer NOT NULL CHECK (request_count > 0),
    -- the provider's progress as last seen, e.g. "processing 120, succeeded 880"
    progress text,
    -- token usage of the stored results (classify.model.Usage), at Batch prices
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    ended_at timestamptz,
    stored_at timestamptz,
    CHECK ((status = 'preparing') OR (status = 'failed') OR (provider_batch_id IS NOT NULL))
);

-- One request per distinct input of a batch; Notifications with the same input_hash share
-- it (the input_hash dedupe of `ofa classify`).
CREATE TABLE classify_batch_requests (
    batch_id bigint NOT NULL REFERENCES classify_batches (id) ON DELETE CASCADE,
    custom_id text NOT NULL CHECK (custom_id ~ '^[a-zA-Z0-9_-]{1,64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    source text NOT NULL,
    notification_ids bigint[] NOT NULL CHECK (cardinality(notification_ids) > 0),
    -- pending: no result handled yet; stored: the result is in ai_classifications (also
    -- an abstain); failed: the request errored, expired or was cancelled (retried by the
    -- next submission, nothing stored)
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'stored', 'failed')),
    error text,
    PRIMARY KEY (batch_id, custom_id)
);

-- "Is this input already waiting in an open batch?"
CREATE INDEX classify_batch_requests_hash_idx ON classify_batch_requests (input_hash);
CREATE INDEX classify_batches_open_idx ON classify_batches (task, model, prompt_version)
    WHERE status IN ('preparing', 'submitted', 'ended');

-- migrate:down
DROP TABLE classify_batch_requests;
DROP TABLE classify_batches;
