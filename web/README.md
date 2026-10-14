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
- Statistics (ticket 23): `lib/stats-query.ts` (pure, client-safe) adds the period to the shared filters: `parseStatsQuery(params)` → `{filters, months}`, `toStatsParams(query)`, `resolvePeriod(query, now)`. `months` = last N Amsterdam calendar months including the current one (default 12, `all` = no lower bound, ignored when `from`/`to` is set). `getStats(db, query, {locale, now?})` in `lib/stats.ts` → `StatsResponse` (shape below); scope `scopeSql("stats")`, one block per Source, never added up (ADR 0005). `lib/stats-tables.ts`: `timeSeriesTable`, `heatmapGrid`, `pairLabel`, `formatMonth` (the numbers behind both the charts and their data tables).

## Routes

- `/{locale}/n/{source}/{key…}`: Notification detail (`app/[locale]/n/[source]/[...key]`). Build links with `notificationPath(locale, source, key)` from `lib/notification-path.ts`:
  - openFDA and RASFF keys are one segment: `/en/n/openfda/H-0015-2027`, `/en/n/rasff/2026.9489`.
  - NVWA keys (URL paths) fill the remaining segments without the leading slash: `/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-…`.
  - Segments are percent-encoded; `keyFromSegments` reverses it.
- `/{locale}/search`: search page (SSR on every request, `noindex`). A plain GET form, so it works without JavaScript; non-canonical query strings (empty fields, `[]` names) redirect to the canonical URL.
- `GET /api/search`: the same search as JSON (`SearchResponse`); also takes `locale` for labels and detail paths.
- `/{locale}/dashboard`: statistics (SSR on every request, en/nl). The client then refetches `/api/stats` on every filter change and replaces the URL (`history.replaceState`), so the address bar is always shareable; the controls are also a GET form for browsers without JavaScript. Charts: Apache ECharts (`components/dashboard/echarts.ts`, tree-shaken `echarts/core` + line/bar/heatmap + SVG renderer), imported on the client after the first paint by `<Chart option label height>`. Every chart has a data table (`<details>`), rendered on the server.
- `GET /api/stats`: the filter parameters of `/api/search` (same parser) plus `months` and `locale`. Response:

  ```text
  { filters,                      // resolved: `from` is set when `months` applies
    period: { months, from, to }, // months: number | null
    months: ["2025-11", …],       // consecutive YYYY-MM, oldest first; every array below is aligned with it
    sources: [{                   // the selected Sources (all three by default), always rasff, nvwa, openfda order
      source, label, total,
      classified: { hazard, product, country },   // Notifications with ≥1 value of that dimension
      monthly: [n, …],
      top: { hazard|product|country: [{ value, label, count }] },   // ≤ 10, count desc
      heatmap: [{ hazard: {value,label}, country: {value,label}, total, counts: [n, …] }]  // ≤ 20 pairs
    }] }
  ```

  Values are RASFF ids (hazard, product) or ISO2 (country), as in the filters. Counts are Notifications; one with several categories counts in each. With `official_only`, AI rows are left out of filters and dimensions but the Notifications still count in `total`/`monthly`.
- Reusable chart parts: `getStats` (e.g. `{filters: NO_FILTERS, months: 12}`), `<Chart>`, `timeSeriesOption`/`heatmapOption`/`topOption` and `SOURCE_COLORS` in `components/dashboard/options.ts`, and the exported `Results` component. Options contain functions, so build them in a client component (as `components/home-charts.tsx` does).
- `/{locale}/alerts`: subscription form; `/{locale}/alerts/confirm#token=…`: confirmation landing page (button → `/api/confirm`). Both `noindex`, available in en/nl/zh.
- `POST /api/subscribe`, `POST /api/confirm`: JSON only (also blocks cross-site form posts). See the route files for bodies and status codes.
- Locales: `en` (default), `nl` and `zh`, always prefixed; `/` redirects by Accept-Language to en/nl only. zh exists only for the sections listed in `localesForPath` (`i18n/routing.ts`, now just `alerts`); other pages call `notFound()` unless `isSiteLocale(locale)`. No locale cookie.
- `/{locale}` (en/nl; ticket 26): home page. Value proposition, "last 7 days" per Source (`getRecentNotifications(db, {locale, now?, perSource?})` in `lib/home.ts`: same scope and `from` filter as search, so each "all … in search" link shows the same Notifications), two chart thumbnails with data tables (monthly time series, RASFF top hazard categories; `components/home-charts.tsx` reuses the dashboard's `<Chart>` and options) and the subscription entry, then the ad box. ISR: the data is loaded in one `'use cache'` function with `cacheLife("hours")` (revalidate 1 h) and `cacheTag("home")`; the page is prerendered at build.
- `/sitemap.xml` (`app/sitemap.ts`, entries from `buildSitemap` in `lib/sitemap.ts`, cached for an hour): home and dashboard (en/nl), `/en/data`, about/privacy/disclaimer/colofon (en/nl/zh), and the 5,000 most recently published shown Notifications (`listSitemapNotifications`) in en and nl with `lastModified` = `last_changed_at`; every multi-locale page carries hreflang alternates (`zh-Hans` for zh). Search and subscription pages are `noindex` and not listed. `/robots.txt` (`app/robots.ts`): allow everything except `/api/`, plus the sitemap URL. Both use `SITE_URL`.
- Layout (`app/[locale]/layout.tsx`): skip link, site name, `SiteNav` (`components/site-nav.tsx`, items from `navItems(locale)` in `lib/site-links.ts`: Home, Dashboard, Search, Subscribe; zh only Subscribe until ticket 32), `LanguageSwitch` (keeps the query string, read when the link is followed, so dashboard filters set with `replaceState` survive) and `SiteFooter` (`components/site-footer.tsx`: links from `footerLinks(locale)`, the disclaimer, Source attribution and "Built by {OWNER_NAME}, founder of SnelVink" with UTM medium `footer`).
- **SnelVink referral rules (spec §11.3).** `snelvinkUrl(medium)` in `lib/referral.ts` builds every SnelVink link (`utm_source=openfoodalerts.nl&utm_medium={footer|about|home_box|zh_box}&utm_campaign=v1`; base `SNELVINK_URL`). The only ad is `<AdBox locale={locale} />` (`components/ad-box.tsx`, server component): place it as the last element of the page content. It renders through `AdBoxGuard`, a client component that checks the real pathname with `isAdBoxAllowed` (`lib/ad-box.ts`) and renders nothing elsewhere: allowed on `/en`, `/nl` and `/zh/*` except the shared zh sections (alerts, legal and data pages). The UTM medium is `zh_box` on zh pages, else `home_box`. `e2e/home.spec.ts` checks that no other page shows it.
- `GET /api/health` (`app/api/health/route.ts`, logic in `lib/health.ts` → `getHealth(db, now)`): per Source `ok`, `problems[]`, `lastSuccessAt`, `lastErrorAt`, `fresh` (last successful ingest ≤ `FRESH_HOURS` = 36 h), `contract {status ok|failed|unreachable|unchecked, checkedAt, error}` (from `ofa probe-contracts`; a passing probe older than 36 h is `contract_stale`), `newNotifications {days: 7, count, lastFirstSeenAt}` and `silent` (RASFF only: 0 new Notifications in 7 days). 200 when every Source is ok, else 503 (also when the database is down). Dynamic (`connection()`), `Cache-Control: no-store`. The text of `sources.last_error` is never exposed.

## Subscriptions (ticket 28)

Private tables `subscriptions`, `email_suppressions`, `email_deliveries` (migration `20261025000700`). `ofa_web` reads and writes the first two and only reads `email_deliveries`; it records confirmation emails through the SECURITY DEFINER function `record_confirm_delivery(subscription_id, provider_message_id)`. `ofa_pipeline` has no access; `ofa_mailer` reads public tables and inserts deliveries, and since ticket 29 sees Subscriptions only through the `sendable_subscriptions` view (below).

Modules to reuse (tickets 29–31):

- `lib/subscriptions/validate.ts`: `parseSubscriptionRequest(body, known)`, `normalizeEmail`, filter types, `SOURCE_CODES`, `ZH_SOURCES`.
- `lib/subscriptions/crypto.ts`: `newConfirmToken`, `tokenHash`, `manageToken(id, secret)`, `emailHash(email, pepper)`, `ipHash`. The formats are documented at the top of the file; the Python mailer must build manage tokens and email hashes the same way.
- `lib/subscriptions/service.ts`: `requestSubscription`, `confirmSubscription`, `isSuppressed(db, email, pepper)`, `confirmUrl`.
- `lib/subscriptions/consent.ts`: `CONSENT_TEXT_VERSION` and the consent texts per version and locale. Bump the version whenever a text changes.
- `lib/subscriptions/catalog.ts`: filter values from the seed tables; `runtime.ts`: env wiring, rate limiters, `loadFilterCatalog()` (cached).
- `lib/email/transport.ts`: `EmailTransport` (`brevo` | `outbox` | `log` via `EMAIL_TRANSPORT`; `createMemoryTransport()` for tests). `lib/email/render.ts`: `renderEmail({locale, subject, blocks, footer})` → plain text + HTML. `lib/email/templates.ts`: `renderConfirmEmail`; strings in `messages/*.json` under `Email`.
- `lib/rate-limit.ts`: in-memory per-IP limiter (single instance only) and `clientIp(headers, CLIENT_IP_HEADER)`.

Environment: `OFA_HASH_PEPPER`, `OFA_TOKEN_SECRET` (required in production), `EMAIL_TRANSPORT`, `BREVO_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_OUTBOX_DIR`, `CLIENT_IP_HEADER`, `SUBSCRIBE_RATE_LIMIT`, `CONFIRM_RATE_LIMIT`, `MANAGE_RATE_LIMIT`, `SITE_URL` (see `.env.example`).

### Manage, unsubscribe, delete (ticket 29)

- Page `/{locale}/alerts/manage/{token}` (en/nl/zh, noindex, `Referrer-Policy: no-referrer`, per request): masked address, status, the same filter fields as the form (`components/subscription-settings.tsx`), an unsubscribe button (`#unsubscribe`) and "delete my data". Opening it changes nothing.
- `GET /api/manage?token=` → `{subscription}`; `POST /api/manage` JSON `{token, locale, filters, include_unclassified, instant_sources}` (same rules as subscribing, via `parseSubscriptionSettings`) → 200 / 400 / 404 / 409 unsubscribed.
- `POST /api/unsubscribe?token=` with form body `List-Unsubscribe=One-Click` (RFC 8058; no cookies or JS) or JSON `{token}` → 200 `{"status":"unsubscribed"}` (idempotent) / 400 / 404. `GET /api/unsubscribe?token=` never unsubscribes: 303 to the manage page `#unsubscribe`.
- `POST /api/delete` JSON `{token}` → deletes every Subscription of that address with its deliveries and adds the email HMAC to `email_suppressions`.
- `POST /api/confirm` now also returns `manage_path`; the confirmation page links to it.
- Modules: `lib/subscriptions/manage.ts` (`findSubscription`, `updateSubscriptionSettings`, `unsubscribe`, `deleteSubscriptionData`, `maskEmail`), `lib/subscriptions/links.ts`, `lib/subscriptions/http.ts` (no-store / no-referrer / noindex responses, rate-limit helper).

**Links in Digest and Instant emails (contract with the Python mailer).** `pipeline/src/openfoodalerts/subscriptions/links.py` and `lib/subscriptions/links.ts` produce identical values; both test suites share the literal test vector.

```text
token        = base64url_nopad(HMAC-SHA256(OFA_TOKEN_SECRET, "manage:v1:" + subscription_id))
manage page  = {SITE_URL}/{subscription.locale}/alerts/manage/{token}
unsubscribe  = {SITE_URL}/api/unsubscribe?token={token}

List-Unsubscribe: <{SITE_URL}/api/unsubscribe?token={token}>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

Put the manage link and the unsubscribe link in the body of every Digest and Instant email as well (spec §10.5). No `mailto:` variant (nobody reads an unsubscribe mailbox). The headers go only on Digest and Instant emails, not on confirmation emails.

**Who may be emailed.** Migration `20261025001110` adds `subscriptions.email_hash` (the web writes it) and the view `sendable_subscriptions` (active and not in `email_suppressions`; rows without `email_hash` are excluded). `ofa_mailer` can read only this view, not `subscriptions` or `email_suppressions`. The mailer selects recipients from the view and checks `is_sendable(conn, id)` again right before each send (`openfoodalerts.subscriptions.sendable`).

**Retention.** `uv run ofa cleanup-subscriptions` (daily) calls the SECURITY DEFINER function `cleanup_subscriptions()` (migration `20261025001100`, EXECUTE for `ofa_mailer` only): pending 7 days after the last request, unsubscribed after 29 days (so always within 30), `email_deliveries` after 12 months. It connects with `MAILER_DATABASE_URL` (falls back to `DATABASE_URL`).

## Tests

- `pnpm test` (vitest): data access against `TEST_DATABASE_URL`, each test in a rolled-back transaction.
- `make smoke` (repo root): loads the openFDA, RASFF and NVWA fixtures (`make web-fixtures`; use a database without other data), builds, starts on `SMOKE_PORT` (3004) and runs Playwright (`e2e/`, chromium only, axe WCAG A/AA check). The test server sends email with `EMAIL_TRANSPORT=outbox` into `e2e/.outbox/` (git-ignored), where `e2e/outbox.ts` reads it back.
- Subscription tests run as `ofa_web` (`SET LOCAL ROLE`, see `lib/test-db.ts`), so they also check the migration's grants.
