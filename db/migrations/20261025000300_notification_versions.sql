-- migrate:up
CREATE TABLE notification_versions (
    notification_id bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    version         integer NOT NULL CHECK (version >= 1),
    raw_record_id   bigint NOT NULL REFERENCES raw_records (id),
    observed_at     timestamptz NOT NULL,
    -- {"field": {"old": ..., "new": ...}}; source_fields keys appear as "source_fields.<key>".
    changed_fields  jsonb NOT NULL DEFAULT '{}',
    is_substantial  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (notification_id, version)
);

-- migrate:down
DROP TABLE notification_versions;
