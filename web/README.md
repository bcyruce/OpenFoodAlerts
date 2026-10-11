# OpenFoodAlerts web

Next.js App Router site (Next 16, Cache Components, next-intl, Drizzle, Tailwind 4). It only reads Postgres (ADR 0001); run it with `make dev` from the repo root, which exports the root `.env`.

## Database access

- The site connects as the read-only role `ofa_web` through `WEB_DATABASE_URL`. `make db-roles` enables its login with `OFA_WEB_PASSWORD` (roles are cluster-wide; the migrations grant SELECT on public tables only, not `raw_records`).
- Table types in `db/generated/` come from `make db-types` (drizzle-kit pull on the migrated `DATABASE_URL`). Never edit them; CI fails if they differ from the migrations.
- Read functions live in `lib/notifications.ts` and take the database as their first argument:
  - `getNotificationDetail(db, source, key)` → `NotificationDetail | null`: official fields, Source attribution, ISO timestamps, `sourceFields`, versions newest first with `changes: {field, old, new}[]`. Returns null when the Notification is missing or its Product type is not in `DISPLAYED_PRODUCT_TYPES` (non-food and pending are never shown).
  - `listRecentNotificationKeys(db, limit)`, `DISPLAYED_PRODUCT_TYPES`.
  - `getDb()` in `lib/db.ts` returns the shared client for `WEB_DATABASE_URL`.
- Filters shared by search and statistics (spec §8):
  - `lib/filters.ts` (pure, client-safe): `parseFilters(params)` → `Filters`, `parseSearchQuery(params)` → `{q, page, filters}`, `toSearchParams(query)` (canonical URL form). `params` is a `URLSearchParams` or a page's `searchParams` object. Parameters: `source`, `hazard` (RASFF hazard category id), `product` (RASFF product category id), `country` (origin ISO2), `risk` (`risk_official` value or `not_graded`), each repeatable with or without `[]`; `from`/`to` (YYYY-MM-DD, Amsterdam days, inclusive); `official_only` (`1`/`true`/`on`). Unusable values are dropped, never an error.
  - `lib/filter-sql.ts`: `FROM_NOTIFICATIONS` (`notifications n JOIN sources s`), `scopeSql("search" | "stats")` (spec §4.3; stats also drop RASFF News), `filtersSql(filters, {omit})` (`omit` one facet to count its values), `provenanceSql(alias, filters)`, `inList`, `rows`.
- `searchNotifications(db, {q, page, filters}, {locale, pageSize?})` in `lib/search.ts` → `SearchResponse`: `{q, filters, page, pageSize, total, pageCount, results, facets}`. Text matching uses the SQL function `notification_search_query(q)` on `search_tsv` (written by the pipeline at parse time) plus `product_text ILIKE` for partial words; facets `source`, `hazard`, `product`, `country`, `risk` are `{value, label, count, selected}[]`.

## Routes

- `/{locale}/n/{source}/{key…}`: Notification detail (`app/[locale]/n/[source]/[...key]`). Build links with `notificationPath(locale, source, key)` from `lib/notification-path.ts`:
  - openFDA and RASFF keys are one segment: `/en/n/openfda/H-0015-2027`, `/en/n/rasff/2026.9489`.
  - NVWA keys (URL paths) fill the remaining segments without the leading slash: `/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-…`.
  - Segments are percent-encoded; `keyFromSegments` reverses it.
- `/{locale}/search`: search page (SSR on every request, `noindex`). A plain GET form, so it works without JavaScript; non-canonical query strings (empty fields, `[]` names) redirect to the canonical URL.
- `GET /api/search`: the same search as JSON (`SearchResponse`); also takes `locale` for labels and detail paths.
- Locales: `en` (default) and `nl`, always prefixed; `/` redirects by Accept-Language. No locale cookie.

## Tests

- `pnpm test` (vitest): data access against `TEST_DATABASE_URL`, each test in a rolled-back transaction.
- `make smoke` (repo root): loads the openFDA, RASFF and NVWA fixtures (`make web-fixtures`; use a database without other data), builds, starts on `SMOKE_PORT` (3004) and runs Playwright (`e2e/`, chromium only, axe WCAG A/AA check).
