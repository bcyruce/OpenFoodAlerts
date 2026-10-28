# Python writes the database, Next.js reads it, SQL migrations own the schema

The ingestion pipeline, classifier and eval harness are Python; the website is Next.js/TypeScript; both talk only through Postgres. Plain SQL migrations (dbmate) are the single source of truth for the schema, and TypeScript types are generated from the database rather than hand-written, so the two languages cannot drift apart.

## Considered Options

- **All Python (FastAPI + Jinja/HTMX):** one language, but an interactive dashboard is harder and existing Node/PM2/Nginx experience goes unused.
- **All TypeScript:** loses pytest and the Python evaluation ecosystem, which are central to this project.
