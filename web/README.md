# OpenFoodAlerts web

Next.js App Router site (Next 16, Cache Components, next-intl, Drizzle, Tailwind 4). It only reads Postgres (ADR 0001); run it with `make dev` from the repo root, which exports the root `.env`.

## Database access

- The site connects as the read-only role `ofa_web` through `WEB_DATABASE_URL`. `make db-roles` enables its login with `OFA_WEB_PASSWORD` (roles are cluster-wide; the migrations grant SELECT on public tables only, not `raw_records`).
- Table types in `db/generated/` come from `make db-types` (drizzle-kit pull on the migrated `DATABASE_URL`). Never edit them; CI fails if they differ from the migrations.
- Read functions live in `lib/notifications.ts` and take the database as their first argument:
  - `getNotificationDetail(db, source, key)` → `NotificationDetail | null`: official fields, Source attribution, ISO timestamps, `sourceFields`, versions newest first with `changes: {field, old, new}[]`. Returns null when the Notification is missing or its Product type is not in `DISPLAYED_PRODUCT_TYPES` (non-food and pending are never shown).
  - `listRecentNotificationKeys(db, limit)`, `DISPLAYED_PRODUCT_TYPES`.
  - `getDb()` in `lib/db.ts` returns the shared client for `WEB_DATABASE_URL`.

## Routes

- `/{locale}/n/{source}/{key…}`: Notification detail (`app/[locale]/n/[source]/[...key]`). Build links with `notificationPath(locale, source, key)` from `lib/notification-path.ts`:
  - openFDA and RASFF keys are one segment: `/en/n/openfda/H-0015-2027`, `/en/n/rasff/2026.9489`.
  - NVWA keys (URL paths) fill the remaining segments without the leading slash: `/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-…`.
  - Segments are percent-encoded; `keyFromSegments` reverses it.
- Locales: `en` (default) and `nl`, always prefixed; `/` redirects by Accept-Language. No locale cookie.
- `GET /api/health` (`app/api/health/route.ts`, logic in `lib/health.ts` → `getHealth(db, now)`): per Source `ok`, `problems[]`, `lastSuccessAt`, `lastErrorAt`, `fresh` (last successful ingest ≤ `FRESH_HOURS` = 36 h), `contract {status ok|failed|unreachable|unchecked, checkedAt, error}` (from `ofa probe-contracts`; a passing probe older than 36 h is `contract_stale`), `newNotifications {days: 7, count, lastFirstSeenAt}` and `silent` (RASFF only: 0 new Notifications in 7 days). 200 when every Source is ok, else 503 (also when the database is down). Dynamic (`connection()`), `Cache-Control: no-store`. The text of `sources.last_error` is never exposed.

## Tests

- `pnpm test` (vitest): data access against `TEST_DATABASE_URL`, each test in a rolled-back transaction.
- `make smoke` (repo root): loads the fixtures (`make web-fixtures`), builds, starts on `SMOKE_PORT` (3004) and runs Playwright (`e2e/`, chromium only, axe WCAG A/AA check).
