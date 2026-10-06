-- migrate:up

-- Child records of a Notification (spec §4.1). Official rows are written by the parser and
-- replaced as a whole whenever the Notification changes; AI rows (provenance = 'ai') belong
-- to the classifier and are never touched by the parser. ai_classification_id gets its
-- foreign key once ai_classifications exists (ticket 16).

CREATE TABLE notification_hazards (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id      bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    -- order within the source record
    position             smallint NOT NULL DEFAULT 0,
    hazard_name          text,
    hazard_category_id   integer REFERENCES hazard_categories (id),
    -- NULL = not determined: RASFF does not say which of several Hazards is primary (spec §16)
    is_primary           boolean,
    analytical_result    text,
    unit                 text,
    max_permitted_level  text,
    sampling_date        date,
    provenance           text NOT NULL CHECK (provenance IN ('official', 'ai')),
    ai_classification_id bigint
);

CREATE INDEX notification_hazards_notification_idx ON notification_hazards (notification_id);
CREATE INDEX notification_hazards_category_idx ON notification_hazards (hazard_category_id);

CREATE TABLE notification_product_categories (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id      bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    position             smallint NOT NULL DEFAULT 0,
    product_category_id  integer NOT NULL REFERENCES product_categories (id),
    provenance           text NOT NULL CHECK (provenance IN ('official', 'ai')),
    ai_classification_id bigint
);

CREATE INDEX notification_product_categories_notification_idx
    ON notification_product_categories (notification_id);
CREATE INDEX notification_product_categories_category_idx
    ON notification_product_categories (product_category_id);
CREATE UNIQUE INDEX notification_product_categories_official_uq
    ON notification_product_categories (notification_id, product_category_id)
    WHERE provenance = 'official';

CREATE TABLE notification_countries (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id      bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    country_iso2         text NOT NULL REFERENCES countries (iso2),
    role                 text NOT NULL
        CHECK (role IN ('origin', 'notifying', 'distribution', 'operator', 'recalling_firm')),
    provenance           text NOT NULL CHECK (provenance IN ('official', 'ai')),
    ai_classification_id bigint
);

CREATE INDEX notification_countries_notification_idx ON notification_countries (notification_id);
CREATE INDEX notification_countries_country_idx ON notification_countries (country_iso2, role);
CREATE UNIQUE INDEX notification_countries_official_uq
    ON notification_countries (notification_id, country_iso2, role)
    WHERE provenance = 'official';

-- RASFF only: measures taken, by country.
CREATE TABLE measures (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id bigint NOT NULL REFERENCES notifications (id) ON DELETE CASCADE,
    position        smallint NOT NULL DEFAULT 0,
    country_iso2    text REFERENCES countries (iso2),
    action_rasff_id integer,
    action_text     text
);

CREATE INDEX measures_notification_idx ON measures (notification_id);

GRANT SELECT ON notification_hazards, notification_product_categories,
    notification_countries, measures TO ofa_web;

-- migrate:down
REVOKE SELECT ON notification_hazards, notification_product_categories,
    notification_countries, measures FROM ofa_web;
DROP TABLE measures;
DROP TABLE notification_countries;
DROP TABLE notification_product_categories;
DROP TABLE notification_hazards;
