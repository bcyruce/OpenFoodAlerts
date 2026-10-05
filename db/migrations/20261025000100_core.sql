-- migrate:up
CREATE TABLE sources (
    id               smallint PRIMARY KEY,
    code             text NOT NULL UNIQUE CHECK (code IN ('rasff', 'nvwa', 'openfda')),
    name             text NOT NULL,
    base_url         text NOT NULL,
    license          text NOT NULL,
    attribution_text text NOT NULL,
    last_success_at  timestamptz,
    last_error       text,
    last_error_at    timestamptz
);

INSERT INTO sources (id, code, name, base_url, license, attribution_text) VALUES
    (1, 'rasff', 'EU RASFF Window', 'https://webgate.ec.europa.eu/rasff-window/',
     'CC BY 4.0 (Commission Decision 2011/833/EU; RASFF-specific terms to be verified)',
     'Source: European Commission – RASFF Window; normalized and classified by OpenFoodAlerts, changes indicated.'),
    (2, 'nvwa', 'NVWA veiligheidswaarschuwingen', 'https://www.nvwa.nl/',
     'CC0 1.0 for text (photos and videos excluded)',
     'Source: Nederlandse Voedsel- en Warenautoriteit (NVWA). Unofficial; not endorsed by NVWA.'),
    (3, 'openfda', 'openFDA food enforcement reports', 'https://api.fda.gov/food/enforcement.json',
     'US federal public domain (CC0 claim to be verified)',
     'Source: U.S. Food and Drug Administration via openFDA. Not endorsed by FDA.');

-- Append-only archive of every fetched response (ADR 0004). Never UPDATE or DELETE.
CREATE TABLE raw_records (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id    smallint NOT NULL REFERENCES sources (id),
    source_key   text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('list', 'detail', 'lookup', 'sitemap')),
    url          text NOT NULL,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    http_status  smallint NOT NULL,
    content_hash text NOT NULL,
    content_type text NOT NULL,
    body         bytea NOT NULL
);

CREATE INDEX raw_records_key_idx ON raw_records (source_id, kind, source_key, id DESC);

CREATE TABLE notifications (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id               smallint NOT NULL REFERENCES sources (id),
    source_key              text NOT NULL,
    source_url              text NOT NULL,
    source_ref              text,
    title                   text NOT NULL,
    published_at            timestamptz,
    source_updated_at       timestamptz,
    first_seen_at           timestamptz NOT NULL DEFAULT now(),
    last_changed_at         timestamptz NOT NULL DEFAULT now(),
    notification_type       text NOT NULL,
    risk_official           text,
    status_official         text,
    product_type            text CHECK (product_type IN ('food', 'feed', 'food contact material', 'non-food')),
    product_type_provenance text NOT NULL CHECK (product_type_provenance IN ('official', 'rule', 'ai', 'pending')),
    product_text            text,
    hazard_text             text,
    summary_source          text,
    -- Source-specific official fields without a column of their own (e.g. FDA recalling firm).
    source_fields           jsonb NOT NULL DEFAULT '{}',
    raw_record_id           bigint NOT NULL REFERENCES raw_records (id),
    parser_version          text NOT NULL,
    current_version         integer NOT NULL DEFAULT 1,
    search_tsv              tsvector,
    UNIQUE (source_id, source_key),
    -- product_type is NULL exactly while the Notification waits for T5.
    CHECK ((product_type IS NULL) = (product_type_provenance = 'pending'))
);

CREATE INDEX notifications_search_idx ON notifications USING gin (search_tsv);
CREATE INDEX notifications_product_text_trgm_idx ON notifications USING gin (product_text gin_trgm_ops);
CREATE INDEX notifications_published_idx ON notifications (source_id, published_at DESC);

-- migrate:down
DROP TABLE notifications;
DROP TABLE raw_records;
DROP TABLE sources;
