-- migrate:up

-- Human review of AI classifications (spec §6.5, ticket 20).
--
-- review_settings: the "low confidence" threshold per task (spec §6.3: chosen from the dev
-- coverage-accuracy curve, ticket 21). A current result whose confidence is below the
-- task's min_confidence is queued; abstains are always queued. A task without a row uses
-- 'medium', i.e. only confidence = 'low' is queued (spec §4.1). 'low' queues abstains
-- only, 'high' queues low and medium.
CREATE TABLE review_settings (
    task           text PRIMARY KEY CHECK (task ~ '^[a-z][a-z0-9_]*$'),
    min_confidence text NOT NULL CHECK (min_confidence IN ('low', 'medium', 'high')),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- The effective value of a classification (spec §6.5: the reviewer's value overrides the
-- model's), as in openfoodalerts.classify.effective.effective_value: a correction's
-- reviewed_value, otherwise the model's value; NULL when that is an abstain (an
-- uncorrected abstained row, or a correction with an abstain_reason: "the text does not
-- say"). For queries that show or count AI values (badges, ticket 24; the Digest's T6
-- summaries): SELECT ai_effective_value(c) FROM ai_classifications c.
CREATE FUNCTION ai_effective_value(c ai_classifications) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN c.review_status = 'corrected' THEN
            CASE WHEN c.reviewed_value ->> 'abstain_reason' IS NULL THEN c.reviewed_value END
        WHEN c.abstained THEN NULL
        ELSE c.value
    END
$$;

-- review_queue: the current result of each (Notification, task) -- the newest row by
-- created_at, then id, the same rule as everywhere else -- when it is unreviewed and
-- abstained or below the threshold, with the Notification text a reviewer needs.
-- Superseded rows (older prompt versions, earlier inputs) never appear: once the input or
-- the prompt changes, the new row is the one to review (ticket 20 decision; the review of
-- an older row stays on that row as history).
CREATE VIEW review_queue AS
SELECT
    c.id AS classification_id,
    c.notification_id,
    c.task,
    CASE WHEN c.abstained THEN 'abstained' ELSE 'low_confidence' END AS reason,
    c.value,
    c.confidence,
    c.abstained,
    c.evidence_span,
    c.model,
    c.prompt_version,
    c.schema_version,
    c.taxonomy_version,
    c.created_at,
    s.code AS source,
    n.source_key,
    n.source_url,
    n.title,
    n.product_text,
    n.hazard_text,
    n.summary_source,
    n.published_at
FROM ai_classifications c
JOIN notifications n ON n.id = c.notification_id
JOIN sources s ON s.id = n.source_id
LEFT JOIN review_settings r ON r.task = c.task
WHERE c.review_status = 'unreviewed'
  AND NOT EXISTS (
      SELECT 1 FROM ai_classifications newer
      WHERE newer.notification_id = c.notification_id AND newer.task = c.task
        AND (newer.created_at, newer.id) > (c.created_at, c.id)
  )
  AND (
      c.abstained
      OR array_position(ARRAY['low', 'medium', 'high'], c.confidence)
         < array_position(ARRAY['low', 'medium', 'high'], coalesce(r.min_confidence, 'medium'))
  );

-- Not public: neither the website nor the mailer reads them. ofa_pipeline (the review page
-- and `ofa review-*` run as the pipeline) reads the queue through the default privileges;
-- the view is read-only, reviews are written to ai_classifications.
REVOKE INSERT, UPDATE, DELETE ON review_queue FROM ofa_pipeline;

-- migrate:down
DROP VIEW review_queue;
DROP FUNCTION ai_effective_value(ai_classifications);
DROP TABLE review_settings;
