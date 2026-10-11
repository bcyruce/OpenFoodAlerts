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
- `/{locale}/alerts`: subscription form; `/{locale}/alerts/confirm#token=…`: confirmation landing page (button → `/api/confirm`). Both `noindex`, available in en/nl/zh.
- `POST /api/subscribe`, `POST /api/confirm`: JSON only (also blocks cross-site form posts). See the route files for bodies and status codes.
- Locales: `en` (default), `nl` and `zh`, always prefixed; `/` redirects by Accept-Language to en/nl only. zh exists only for the sections listed in `localesForPath` (`i18n/routing.ts`, now just `alerts`); other pages call `notFound()` unless `isSiteLocale(locale)`. No locale cookie.

## Subscriptions (ticket 28)

Private tables `subscriptions`, `email_suppressions`, `email_deliveries` (migration `20261025000700`). `ofa_web` reads and writes the first two and only reads `email_deliveries`; it records confirmation emails through the SECURITY DEFINER function `record_confirm_delivery(subscription_id, provider_message_id)`. `ofa_pipeline` has no access; `ofa_mailer` reads Subscriptions and public tables and inserts deliveries.

Modules to reuse (tickets 29–31):

- `lib/subscriptions/validate.ts`: `parseSubscriptionRequest(body, known)`, `normalizeEmail`, filter types, `SOURCE_CODES`, `ZH_SOURCES`.
- `lib/subscriptions/crypto.ts`: `newConfirmToken`, `tokenHash`, `manageToken(id, secret)`, `emailHash(email, pepper)`, `ipHash`. The formats are documented at the top of the file; the Python mailer must build manage tokens and email hashes the same way.
- `lib/subscriptions/service.ts`: `requestSubscription`, `confirmSubscription`, `isSuppressed(db, email, pepper)`, `confirmUrl`.
- `lib/subscriptions/consent.ts`: `CONSENT_TEXT_VERSION` and the consent texts per version and locale. Bump the version whenever a text changes.
- `lib/subscriptions/catalog.ts`: filter values from the seed tables; `runtime.ts`: env wiring, rate limiters, `loadFilterCatalog()` (cached).
- `lib/email/transport.ts`: `EmailTransport` (`brevo` | `outbox` | `log` via `EMAIL_TRANSPORT`; `createMemoryTransport()` for tests). `lib/email/render.ts`: `renderEmail({locale, subject, blocks, footer})` → plain text + HTML. `lib/email/templates.ts`: `renderConfirmEmail`; strings in `messages/*.json` under `Email`.
- `lib/rate-limit.ts`: in-memory per-IP limiter (single instance only) and `clientIp(headers, CLIENT_IP_HEADER)`.

Environment: `OFA_HASH_PEPPER`, `OFA_TOKEN_SECRET` (required in production), `EMAIL_TRANSPORT`, `BREVO_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_OUTBOX_DIR`, `CLIENT_IP_HEADER`, `SUBSCRIBE_RATE_LIMIT`, `CONFIRM_RATE_LIMIT`, `SITE_URL` (see `.env.example`).

## Tests

- `pnpm test` (vitest): data access against `TEST_DATABASE_URL`, each test in a rolled-back transaction.
- `make smoke` (repo root): loads the openFDA, RASFF and NVWA fixtures (`make web-fixtures`; use a database without other data), builds, starts on `SMOKE_PORT` (3004) and runs Playwright (`e2e/`, chromium only, axe WCAG A/AA check). The test server sends email with `EMAIL_TRANSPORT=outbox` into `e2e/.outbox/` (git-ignored), where `e2e/outbox.ts` reads it back.
- Subscription tests run as `ofa_web` (`SET LOCAL ROLE`, see `lib/test-db.ts`), so they also check the migration's grants.
