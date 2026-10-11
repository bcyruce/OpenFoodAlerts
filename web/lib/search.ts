/**
 * Full-text search over Notifications with facet counts (spec §8 `/api/search`, §9 `/search`).
 *
 * Matching: `search_tsv @@ notification_search_query(q)` (migration 20261025000800_search:
 * English, Dutch and unstemmed readings, websearch syntax), or, for queries of 3+
 * characters, `product_text ILIKE %q%` (pg_trgm index) so that partial words in product
 * names match too. Results are newest first. Facets count every value as if its own filter
 * were not set, so a visitor can widen a selection; selected values always appear.
 */
import { sql, type SQL } from "drizzle-orm";
import {
  filtersSql,
  FROM_NOTIFICATIONS,
  inList,
  provenanceSql,
  rows,
  scopeSql,
  type FilterFacet,
} from "./filter-sql";
import { NOT_GRADED, type Filters, type SearchQuery } from "./filters";
import { notificationPath } from "./notification-path";
import type { DisplayedProductType, Reader } from "./notifications";

export const PAGE_SIZE = 20;

export type Provenance = "official" | "ai";

/** A Hazard category, Product category or origin country of one Notification. */
export type ClassifiedValue = { value: string; label: string; provenance: Provenance };

export type SearchResult = {
  source: string;
  sourceKey: string;
  /** Detail page in the requested locale. */
  path: string;
  title: string;
  /** ISO 8601 */
  publishedAt: string | null;
  notificationType: string;
  /** null: the Source does not grade (NVWA, ADR 0006). */
  riskOfficial: string | null;
  productType: DisplayedProductType;
  productTypeProvenance: string;
  productText: string | null;
  hazardText: string | null;
  /** Official values first; AI values are left out when official_only is on. */
  hazardCategories: ClassifiedValue[];
  productCategories: ClassifiedValue[];
  originCountries: ClassifiedValue[];
};

export type FacetValue = { value: string; label: string; count: number; selected: boolean };

export type SearchResponse = {
  q: string;
  filters: Filters;
  page: number;
  pageSize: number;
  total: number;
  pageCount: number;
  results: SearchResult[];
  facets: Record<FilterFacet, FacetValue[]>;
};

export const SOURCE_LABELS: Record<string, string> = {
  rasff: "RASFF",
  nvwa: "NVWA",
  openfda: "openFDA",
};

const NOT_GRADED_LABELS: Record<string, string> = { en: "Not graded", nl: "Niet ingedeeld" };

type Names = { name_en: string; name_nl: string | null };

function categoryLabel(locale: string, names: Names): string {
  return (locale === "nl" ? names.name_nl : null) ?? names.name_en;
}

function countryLabel(locale: string, iso2: string, names: Names): string {
  if (locale === "en") return names.name_en;
  if (locale === "nl" && names.name_nl) return names.name_nl;
  // The RASFF dictionary has no Dutch names yet; ICU has them for ISO codes.
  try {
    if (/^[A-Z]{2}$/.test(iso2)) {
      const name = new Intl.DisplayNames([locale], { type: "region", fallback: "none" }).of(iso2);
      if (name) return name;
    }
  } catch {
    // not a region code ICU knows
  }
  return names.name_en;
}

function iso(value: string | Date | null): string | null {
  return value === null ? null : new Date(value).toISOString();
}

function json<T>(value: unknown): T {
  return (typeof value === "string" ? JSON.parse(value) : value) as T;
}

function escapeLike(text: string): string {
  return text.replace(/[\\%_]/g, (c) => `\\${c}`);
}

/** The text-query condition (TRUE without a query). */
function textSql(q: string): SQL {
  if (!q) return sql`TRUE`;
  const fts = sql`n.search_tsv @@ notification_search_query(${q})`;
  if (q.length < 3) return fts;
  return sql`(${fts} OR n.product_text ILIKE ${`%${escapeLike(q)}%`})`;
}

function whereSql(query: SearchQuery, omit?: FilterFacet): SQL {
  return sql`${scopeSql("search")} AND ${textSql(query.q)} AND ${filtersSql(query.filters, { omit })}`;
}

type ResultRow = {
  source: string;
  source_key: string;
  title: string;
  published_at: string | Date | null;
  notification_type: string;
  risk_official: string | null;
  product_type: DisplayedProductType;
  product_type_provenance: string;
  product_text: string | null;
  hazard_text: string | null;
  hazard_categories: unknown;
  product_categories: unknown;
  origin_countries: unknown;
};

type ChildRow = Names & { value: string; provenance: Provenance };

/** Distinct child values of `n`, official first, then in Source order. */
function childrenSql(from: SQL, value: SQL, filters: Filters, alias: string, extra = sql``): SQL {
  return sql`(
    SELECT coalesce(json_agg(json_build_object(
             'value', x.value, 'name_en', x.name_en, 'name_nl', x.name_nl,
             'provenance', x.provenance)
           ORDER BY x.provenance = 'official' DESC, x.pos, x.value), '[]'::json)
    FROM (
      SELECT ${value} AS value, d.name_en, d.name_nl, ${sql.raw(alias)}.provenance,
             min(${sql.raw(alias)}.id) AS pos
      FROM ${from}
      WHERE ${sql.raw(alias)}.notification_id = n.id ${extra} ${provenanceSql(alias, filters)}
      GROUP BY 1, 2, 3, 4
    ) x)`;
}

async function pageOfResults(
  db: Reader,
  query: SearchQuery,
  locale: string,
  pageSize: number,
): Promise<SearchResult[]> {
  const f = query.filters;
  const found = await rows<ResultRow>(
    db,
    sql`
    SELECT s.code AS source, n.source_key, n.title, n.published_at, n.notification_type,
           n.risk_official, n.product_type, n.product_type_provenance, n.product_text,
           n.hazard_text,
           ${childrenSql(
             sql`notification_hazards h JOIN hazard_categories d ON d.id = h.hazard_category_id`,
             sql`d.rasff_id::text`,
             f,
             "h",
           )} AS hazard_categories,
           ${childrenSql(
             sql`notification_product_categories pc JOIN product_categories d ON d.id = pc.product_category_id`,
             sql`d.rasff_id::text`,
             f,
             "pc",
           )} AS product_categories,
           ${childrenSql(
             sql`notification_countries c JOIN countries d ON d.iso2 = c.country_iso2`,
             sql`d.iso2`,
             f,
             "c",
             sql`AND c.role = 'origin'`,
           )} AS origin_countries
    FROM ${FROM_NOTIFICATIONS}
    WHERE ${whereSql(query)}
    ORDER BY n.published_at DESC NULLS LAST, n.id DESC
    LIMIT ${pageSize} OFFSET ${(query.page - 1) * pageSize}`,
  );
  const category = (list: unknown) =>
    json<ChildRow[]>(list).map((c) => ({
      value: c.value,
      label: categoryLabel(locale, c),
      provenance: c.provenance,
    }));
  return found.map((r) => ({
    source: r.source,
    sourceKey: r.source_key,
    path: notificationPath(locale, r.source, r.source_key),
    title: r.title,
    publishedAt: iso(r.published_at),
    notificationType: r.notification_type,
    riskOfficial: r.risk_official,
    productType: r.product_type,
    productTypeProvenance: r.product_type_provenance,
    productText: r.product_text,
    hazardText: r.hazard_text,
    hazardCategories: category(r.hazard_categories),
    productCategories: category(r.product_categories),
    originCountries: json<ChildRow[]>(r.origin_countries).map((c) => ({
      value: c.value,
      label: countryLabel(locale, c.value, c),
      provenance: c.provenance,
    })),
  }));
}

async function countAll(db: Reader, query: SearchQuery): Promise<number> {
  const [row] = await rows<{ count: number }>(
    db,
    sql`SELECT count(*)::int AS count FROM ${FROM_NOTIFICATIONS} WHERE ${whereSql(query)}`,
  );
  return row?.count ?? 0;
}

type FacetRow = { value: string; count: number; name_en?: string; name_nl?: string | null };

function facetCountSql(query: SearchQuery, facet: FilterFacet): SQL {
  const f = query.filters;
  const where = whereSql(query, facet);
  switch (facet) {
    case "source":
      return sql`SELECT s.code AS value, count(*)::int AS count
        FROM ${FROM_NOTIFICATIONS} WHERE ${where} GROUP BY s.code`;
    case "risk":
      return sql`SELECT coalesce(n.risk_official, ${NOT_GRADED}) AS value, count(*)::int AS count
        FROM ${FROM_NOTIFICATIONS} WHERE ${where} GROUP BY 1`;
    case "hazard":
      return sql`SELECT d.rasff_id::text AS value, d.name_en, d.name_nl,
          count(DISTINCT n.id)::int AS count
        FROM ${FROM_NOTIFICATIONS}
        JOIN notification_hazards h ON h.notification_id = n.id ${provenanceSql("h", f)}
        JOIN hazard_categories d ON d.id = h.hazard_category_id
        WHERE ${where} GROUP BY d.id`;
    case "product":
      return sql`SELECT d.rasff_id::text AS value, d.name_en, d.name_nl,
          count(DISTINCT n.id)::int AS count
        FROM ${FROM_NOTIFICATIONS}
        JOIN notification_product_categories pc ON pc.notification_id = n.id ${provenanceSql("pc", f)}
        JOIN product_categories d ON d.id = pc.product_category_id
        WHERE ${where} GROUP BY d.id`;
    case "country":
      return sql`SELECT d.iso2 AS value, d.name_en, d.name_nl, count(DISTINCT n.id)::int AS count
        FROM ${FROM_NOTIFICATIONS}
        JOIN notification_countries c ON c.notification_id = n.id AND c.role = 'origin'
          ${provenanceSql("c", f)}
        JOIN countries d ON d.iso2 = c.country_iso2
        WHERE ${where} GROUP BY d.iso2`;
  }
}

/** Names of selected values that matched nothing, so they can still be shown. */
async function selectedNames(
  db: Reader,
  facet: FilterFacet,
  values: string[],
): Promise<FacetRow[]> {
  if (values.length === 0) return [];
  const list = inList(values);
  switch (facet) {
    case "hazard":
      return rows(db, sql`SELECT rasff_id::text AS value, name_en, name_nl, 0 AS count
        FROM hazard_categories WHERE rasff_id::text IN (${list})`);
    case "product":
      return rows(db, sql`SELECT rasff_id::text AS value, name_en, name_nl, 0 AS count
        FROM product_categories WHERE rasff_id::text IN (${list})`);
    case "country":
      return rows(db, sql`SELECT iso2 AS value, name_en, name_nl, 0 AS count
        FROM countries WHERE iso2 IN (${list})`);
    default:
      return values.map((value) => ({ value, count: 0 }));
  }
}

function selectedValues(filters: Filters, facet: FilterFacet): string[] {
  const values = {
    source: filters.sources,
    hazard: filters.hazardCategories,
    product: filters.productCategories,
    country: filters.countries,
    risk: filters.risks,
  }[facet];
  return values.map(String);
}

function facetLabel(locale: string, facet: FilterFacet, row: FacetRow): string {
  const names = { name_en: row.name_en ?? row.value, name_nl: row.name_nl ?? null };
  switch (facet) {
    case "source":
      return SOURCE_LABELS[row.value] ?? row.value;
    case "risk":
      return row.value === NOT_GRADED ? (NOT_GRADED_LABELS[locale] ?? "Not graded") : row.value;
    case "country":
      return countryLabel(locale, row.value, names);
    default:
      return categoryLabel(locale, names);
  }
}

async function facetValues(
  db: Reader,
  query: SearchQuery,
  facet: FilterFacet,
  locale: string,
): Promise<FacetValue[]> {
  const counted = await rows<FacetRow>(db, facetCountSql(query, facet));
  const selected = selectedValues(query.filters, facet);
  const missing = selected.filter((v) => !counted.some((r) => r.value === v));
  const all = [...counted, ...(await selectedNames(db, facet, missing))];
  return all
    .map((row) => ({
      value: row.value,
      label: facetLabel(locale, facet, row),
      count: row.count,
      selected: selected.includes(row.value),
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, locale));
}

const FACETS: FilterFacet[] = ["source", "hazard", "product", "country", "risk"];

export async function searchNotifications(
  db: Reader,
  query: SearchQuery,
  options: { locale: string; pageSize?: number },
): Promise<SearchResponse> {
  const { locale } = options;
  const pageSize = options.pageSize ?? PAGE_SIZE;
  const [total, results, ...facetLists] = await Promise.all([
    countAll(db, query),
    pageOfResults(db, query, locale, pageSize),
    ...FACETS.map((facet) => facetValues(db, query, facet, locale)),
  ]);
  return {
    q: query.q,
    filters: query.filters,
    page: query.page,
    pageSize,
    total,
    pageCount: Math.ceil(total / pageSize),
    results,
    facets: Object.fromEntries(FACETS.map((facet, i) => [facet, facetLists[i]])) as Record<
      FilterFacet,
      FacetValue[]
    >,
  };
}
