-- migrate:up

-- Evaluation set, Labels and eval runs (spec §4.1, §7; ticket 12).
--
-- The committed CSVs (eval/items.csv, eval/labels.csv) are the published, frozen copies;
-- these tables mirror them so SQL and the /evaluation page can join them to Notifications.
-- `ofa eval-sample` writes eval_items; ticket 15's harness writes eval_runs.

-- One sampled Notification. id is stable and content-derived ("nv-1a2b3c4d": Source prefix
-- + sha256(source_key)[:8]), so an item keeps its id when the sample is re-run unchanged.
-- split is dev or test; the RASFF noise audit set and the second-annotator agreement subset
-- are flags on top of the split (spec §7.1 lists noise_audit as a split, but the RASFF 60
-- are also part of dev 100 / test 200, so it cannot be a separate split value).
CREATE TABLE eval_items (
    id              text PRIMARY KEY CHECK (id ~ '^(nv|fd|ra)-[0-9a-f]{8}$'),
    notification_id bigint NOT NULL REFERENCES notifications (id),
    source_code     text NOT NULL CHECK (source_code IN ('rasff', 'nvwa', 'openfda')),
    split           text NOT NULL CHECK (split IN ('dev', 'test')),
    noise_audit     boolean NOT NULL DEFAULT false,
    agreement       boolean NOT NULL DEFAULT false,
    -- "<source>:<hazard group>", the sampling stratum (pre-label, not a Label)
    stratum         text NOT NULL,
    -- frozen model input in the source language (eval/README.md defines it per Source)
    input_snapshot  jsonb NOT NULL,
    -- active items form the eval set; an item labelled non-food is excluded and replaced
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'excluded')),
    replaced_by     text REFERENCES eval_items (id),
    taxonomy_version text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (notification_id),
    CHECK (noise_audit = false OR source_code = 'rasff')
);

-- One Label: the annotator's value for one task of one item (spec §6.1 task names).
-- value is the label text ("allergens", "NL", "unknown", a verbatim span, "unsure", ...).
CREATE TABLE eval_labels (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_item_id      text NOT NULL REFERENCES eval_items (id),
    task              text NOT NULL CHECK (task IN ('hazard_category', 'product_category',
                          'hazard', 'origin_country', 'product_type')),
    value             text NOT NULL,
    annotator         text NOT NULL CHECK (annotator IN ('A', 'B')),
    guideline_version text NOT NULL,
    labelled_at       timestamptz NOT NULL,
    UNIQUE (eval_item_id, task, annotator, guideline_version)
);

-- One harness run of one model/prompt on one split and task (spec §7.3 latest.json).
CREATE TABLE eval_runs (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    git_sha          text NOT NULL,
    model            text NOT NULL,
    prompt_version   text NOT NULL,
    taxonomy_version text NOT NULL,
    split            text NOT NULL CHECK (split IN ('dev', 'test')),
    task             text NOT NULL,
    metrics          jsonb NOT NULL,
    confusion_matrix jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX eval_runs_created_idx ON eval_runs (task, split, created_at DESC);

-- Eval items and Labels are published data (CC BY 4.0) and runs feed /evaluation.
-- ofa_pipeline gets its privileges from the default privileges of migration 0350.
GRANT SELECT ON eval_items, eval_labels, eval_runs TO ofa_web;

-- migrate:down
REVOKE SELECT ON eval_items, eval_labels, eval_runs FROM ofa_web;
DROP TABLE eval_runs;
DROP TABLE eval_labels;
DROP TABLE eval_items;
