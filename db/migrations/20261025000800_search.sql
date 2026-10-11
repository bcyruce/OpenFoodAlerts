-- migrate:up

-- Full-text search over Notifications (spec §4.1, §8, ticket 22).
--
-- The document mixes English (RASFF, openFDA) and Dutch (NVWA) text. Each text is indexed
-- twice: stemmed in its Source's language and unstemmed ('simple', which also keeps stop
-- words, brand names and references such as 2026.9489). Accents are removed first, so
-- "turkiye" finds "Türkiye". A query is parsed with websearch syntax ("quoted phrase",
-- OR, -word) in English, Dutch and simple and the three are ORed: every word of the query
-- must match under at least one of these readings.
--
-- The pipeline writes search_tsv with notification_search_tsv(id) whenever it writes a
-- Notification (parse/store.py); the UPDATE at the end backfills existing rows. Changing
-- these functions needs a new migration that redefines them and backfills again.

-- unaccent is a trusted extension: the database owner can create it without superuser.
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Language of a Source's own text.
CREATE FUNCTION search_text_config(source_code text) RETURNS regconfig
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN CASE source_code
        WHEN 'nvwa' THEN 'pg_catalog.dutch'::regconfig
        ELSE 'pg_catalog.english'::regconfig
    END;

-- One weighted part of a search document: stemmed and unstemmed lexemes, accents removed.
CREATE FUNCTION search_document_part(config regconfig, weight "char", body text)
    RETURNS tsvector
    LANGUAGE sql STABLE PARALLEL SAFE
    RETURN setweight(
            to_tsvector(config, public.unaccent('public.unaccent'::regdictionary, coalesce(body, ''))),
            weight)
        || setweight(
            to_tsvector('pg_catalog.simple',
                public.unaccent('public.unaccent'::regdictionary, coalesce(body, ''))),
            weight);

-- The search document of one Notification: title and reference (A), Hazard text and
-- official Hazard names (B), product text (C), the Source's summary (D). AI-made Hazards
-- are not part of it, so a text search only ever matches official text.
CREATE FUNCTION notification_search_tsv(notification_id bigint) RETURNS tsvector
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$
        SELECT search_document_part(c.config, 'A', concat_ws(' ', n.title, n.source_key))
            || search_document_part(c.config, 'B', concat_ws(' ', n.hazard_text, h.names))
            || search_document_part(c.config, 'C', n.product_text)
            || search_document_part(c.config, 'D', n.summary_source)
        FROM notifications n
        JOIN sources s ON s.id = n.source_id
        CROSS JOIN LATERAL (SELECT search_text_config(s.code) AS config) c
        LEFT JOIN LATERAL (
            SELECT string_agg(hazard_name, ' ' ORDER BY position, id) AS names
            FROM notification_hazards
            WHERE notification_hazards.notification_id = n.id AND provenance = 'official'
        ) h ON true
        WHERE n.id = notification_search_tsv.notification_id
    $$;

-- A visitor's query as a tsquery to match against search_tsv (websearch syntax).
CREATE FUNCTION notification_search_query(q text) RETURNS tsquery
    LANGUAGE sql STABLE PARALLEL SAFE
    RETURN websearch_to_tsquery('pg_catalog.english', public.unaccent('public.unaccent'::regdictionary, q))
        || websearch_to_tsquery('pg_catalog.dutch', public.unaccent('public.unaccent'::regdictionary, q))
        || websearch_to_tsquery('pg_catalog.simple', public.unaccent('public.unaccent'::regdictionary, q));

GRANT EXECUTE ON FUNCTION notification_search_query(text) TO ofa_web;

-- Search results are listed newest first.
CREATE INDEX notifications_published_at_idx ON notifications (published_at DESC, id DESC);

UPDATE notifications SET search_tsv = notification_search_tsv(id);

-- migrate:down
DROP INDEX notifications_published_at_idx;
UPDATE notifications SET search_tsv = NULL;
REVOKE EXECUTE ON FUNCTION notification_search_query(text) FROM ofa_web;
DROP FUNCTION notification_search_query(text);
DROP FUNCTION notification_search_tsv(bigint);
DROP FUNCTION search_document_part(regconfig, "char", text);
DROP FUNCTION search_text_config(text);
DROP EXTENSION IF EXISTS unaccent;
