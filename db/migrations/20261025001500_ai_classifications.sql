-- migrate:up

-- AI classifications (spec §4.1, §6; ticket 16). One row per model output for one
-- Notification and task, with the provenance needed to reproduce it: model, prompt,
-- output schema and taxonomy versions, and the input_hash of the exact model input
-- (openfoodalerts.classify.input_hash). Rows are never updated by the classifier: a new
-- prompt version or a changed input gives a new row; the newest row per
-- (notification_id, task) is the current one. Human review (ticket 20) writes
-- review_status / reviewed_value only.
--
-- task is a spec §6.1 task name (hazard_category for T1; T2-T6 follow). value is the
-- task's output object, e.g. T1 {"category": "allergens"}; an abstained row has
-- {"category": null, "abstain_reason": "...", "model_output": {...}} so a reviewer sees
-- what the model said. confidence and evidence_span are NULL when abstained.
CREATE TABLE ai_classifications (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id  bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    task             text NOT NULL CHECK (task ~ '^[a-z][a-z0-9_]*$'),
    value            jsonb NOT NULL,
    confidence       text CHECK (confidence IN ('high', 'medium', 'low')),
    abstained        boolean NOT NULL,
    evidence_span    text,
    model            text NOT NULL,
    prompt_version   text NOT NULL,
    schema_version   text NOT NULL,
    taxonomy_version text,
    input_hash       text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    created_at       timestamptz NOT NULL DEFAULT now(),
    review_status    text NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'approved', 'corrected')),
    reviewed_value   jsonb,
    reviewed_at      timestamptz,
    UNIQUE (notification_id, task, model, prompt_version, input_hash),
    CHECK (abstained OR confidence IS NOT NULL),
    CHECK (review_status <> 'corrected' OR reviewed_value IS NOT NULL)
);

-- current row per Notification and task; badges and the Digest read it
CREATE INDEX ai_classifications_current_idx
    ON ai_classifications (notification_id, task, created_at DESC);
-- input_hash dedupe: the same model input is never sent twice
CREATE INDEX ai_classifications_hash_idx
    ON ai_classifications (task, model, prompt_version, input_hash);

-- Rows derived from an AI classification disappear with it: without the classification
-- they would have no provenance.
ALTER TABLE notification_hazards
    ADD CONSTRAINT notification_hazards_ai_classification_fk
    FOREIGN KEY (ai_classification_id) REFERENCES ai_classifications (id) ON DELETE CASCADE;
ALTER TABLE notification_product_categories
    ADD CONSTRAINT notification_product_categories_ai_classification_fk
    FOREIGN KEY (ai_classification_id) REFERENCES ai_classifications (id) ON DELETE CASCADE;
ALTER TABLE notification_countries
    ADD CONSTRAINT notification_countries_ai_classification_fk
    FOREIGN KEY (ai_classification_id) REFERENCES ai_classifications (id) ON DELETE CASCADE;

CREATE INDEX notification_hazards_ai_classification_idx
    ON notification_hazards (ai_classification_id) WHERE ai_classification_id IS NOT NULL;
CREATE INDEX notification_product_categories_ai_classification_idx
    ON notification_product_categories (ai_classification_id)
    WHERE ai_classification_id IS NOT NULL;
CREATE INDEX notification_countries_ai_classification_idx
    ON notification_countries (ai_classification_id) WHERE ai_classification_id IS NOT NULL;

-- AI classifications are public (badges, ticket 24) and feed the emails (T6 summaries,
-- `mail/summaries.py`). ofa_pipeline gets its rights from the default privileges.
GRANT SELECT ON ai_classifications TO ofa_web, ofa_mailer;

-- migrate:down
REVOKE SELECT ON ai_classifications FROM ofa_web, ofa_mailer;
-- AI rows cannot outlive their classifications (they would lose their provenance).
DELETE FROM notification_hazards WHERE ai_classification_id IS NOT NULL;
DELETE FROM notification_product_categories WHERE ai_classification_id IS NOT NULL;
DELETE FROM notification_countries WHERE ai_classification_id IS NOT NULL;
DROP INDEX notification_countries_ai_classification_idx;
DROP INDEX notification_product_categories_ai_classification_idx;
DROP INDEX notification_hazards_ai_classification_idx;
ALTER TABLE notification_countries DROP CONSTRAINT notification_countries_ai_classification_fk;
ALTER TABLE notification_product_categories
    DROP CONSTRAINT notification_product_categories_ai_classification_fk;
ALTER TABLE notification_hazards DROP CONSTRAINT notification_hazards_ai_classification_fk;
DROP TABLE ai_classifications;
