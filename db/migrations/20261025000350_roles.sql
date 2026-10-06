-- migrate:up
-- Database roles (spec §11.2). Roles are cluster-wide, so they are created only if missing
-- and left in place on rollback. They start NOLOGIN; each environment enables login and
-- sets a password outside of migrations.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ofa_pipeline') THEN
        CREATE ROLE ofa_pipeline NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ofa_web') THEN
        CREATE ROLE ofa_web NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ofa_mailer') THEN
        CREATE ROLE ofa_mailer NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO ofa_pipeline, ofa_web, ofa_mailer;

-- The pipeline reads and writes every table except the private subscription tables,
-- which revoke its access when they are created.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ofa_pipeline;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ofa_pipeline;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ofa_pipeline;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ofa_pipeline;

-- The website reads public tables only, granted table by table: every migration that
-- adds a public table grants SELECT on it to ofa_web. raw_records is not public (RASFF
-- raw responses contain authority contact details, spec §3.1).
GRANT SELECT ON sources, notifications, notification_versions,
    countries, hazard_categories, product_categories TO ofa_web;

-- migrate:down
REVOKE SELECT ON sources, notifications, notification_versions,
    countries, hazard_categories, product_categories FROM ofa_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM ofa_pipeline;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM ofa_pipeline;
REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM ofa_pipeline;
REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM ofa_pipeline;
REVOKE USAGE ON SCHEMA public FROM ofa_pipeline, ofa_web, ofa_mailer;
