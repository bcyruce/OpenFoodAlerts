/**
 * Filters shared by `/search`, `/api/search`, `/dashboard` and `/api/stats` (spec §8).
 *
 * URL parameters: `source`, `hazard`, `product`, `country`, `risk` (each repeatable, also
 * accepted with a `[]` suffix), `from`, `to` (YYYY-MM-DD, Europe/Amsterdam calendar days,
 * both inclusive) and `official_only`. Search adds `q` and `page`.
 *
 * Parsing never fails: values that cannot be used are dropped, so a hand-edited or stale
 * URL still shows results. Pure and safe for client components; the SQL for these filters
 * is in `filter-sql.ts`.
 */

export const SOURCES = ["rasff", "nvwa", "openfda"] as const;
export type FilterSource = (typeof SOURCES)[number];

/** `risk` value for Notifications without an official severity (NVWA, ADR 0006). */
export const NOT_GRADED = "not_graded";

export type Filters = {
  /** Source codes. */
  sources: FilterSource[];
  /** Hazard categories by RASFF id (`hazard_categories.rasff_id`, as in Subscription filters). */
  hazardCategories: number[];
  /** Product categories by RASFF id. */
  productCategories: number[];
  /** Origin countries, ISO 3166-1 alpha-2 (RASFF codes such as XK included). */
  countries: string[];
  /** Official severity (`risk_official`) values, or NOT_GRADED. */
  risks: string[];
  /** First and last calendar day of `published_at`, YYYY-MM-DD. */
  from: string | null;
  to: string | null;
  /** Use official values only: AI classifications are left out (S3). */
  officialOnly: boolean;
};

export type SearchQuery = {
  /** Text query in websearch syntax ("phrase", OR, -word); empty for none. */
  q: string;
  /** 1-based. */
  page: number;
  filters: Filters;
};

export const NO_FILTERS: Filters = {
  sources: [],
  hazardCategories: [],
  productCategories: [],
  countries: [],
  risks: [],
  from: null,
  to: null,
  officialOnly: false,
};

export const MAX_PAGE = 500;
export const MAX_QUERY_LENGTH = 200;
const MAX_VALUE_LENGTH = 100;

/** A URLSearchParams, or the `searchParams` object a Next.js page receives. */
export type RawParams = URLSearchParams | Record<string, string | string[] | undefined>;

function all(params: RawParams, name: string): string[] {
  if (params instanceof URLSearchParams) {
    return [...params.getAll(name), ...params.getAll(`${name}[]`)];
  }
  return [params[name], params[`${name}[]`]].flatMap((v) =>
    v === undefined ? [] : Array.isArray(v) ? v : [v],
  );
}

function first(params: RawParams, name: string): string | undefined {
  return all(params, name)[0];
}

function unique<T extends string | number>(values: T[]): T[] {
  return [...new Set(values)].sort((a, b) =>
    typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b)),
  );
}

function ids(values: string[]): number[] {
  return unique(
    values
      .filter((v) => /^\d{1,9}$/.test(v.trim()))
      .map((v) => Number(v.trim()))
      .filter((n) => n > 0),
  );
}

function day(value: string | undefined): string | null {
  const v = value?.trim() ?? "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const date = new Date(`${v}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === v ? v : null;
}

function isOn(value: string | undefined): boolean {
  return ["1", "true", "on"].includes(value?.trim().toLowerCase() ?? "");
}

export function parseFilters(params: RawParams): Filters {
  let from = day(first(params, "from"));
  let to = day(first(params, "to"));
  if (from && to && from > to) [from, to] = [to, from];
  return {
    sources: unique(
      all(params, "source")
        .map((v) => v.trim().toLowerCase())
        .filter((v): v is FilterSource => (SOURCES as readonly string[]).includes(v)),
    ),
    hazardCategories: ids(all(params, "hazard")),
    productCategories: ids(all(params, "product")),
    countries: unique(
      all(params, "country")
        .map((v) => v.trim().toUpperCase())
        .filter((v) => /^[A-Z]{2,10}$/.test(v)),
    ),
    risks: unique(
      all(params, "risk")
        .map((v) => v.trim())
        .filter((v) => v.length > 0 && v.length <= MAX_VALUE_LENGTH),
    ),
    from,
    to,
    officialOnly: isOn(first(params, "official_only")),
  };
}

export function parseSearchQuery(params: RawParams): SearchQuery {
  const page = Number(first(params, "page")?.trim());
  return {
    q: (first(params, "q") ?? "").trim().slice(0, MAX_QUERY_LENGTH),
    page: Number.isInteger(page) && page >= 1 ? Math.min(page, MAX_PAGE) : 1,
    filters: parseFilters(params),
  };
}

/** Canonical URL parameters (no `[]` suffix); empty values and page 1 are left out. */
export function toSearchParams(query: SearchQuery): URLSearchParams {
  const { q, page, filters: f } = query;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  for (const v of f.sources) params.append("source", v);
  for (const v of f.hazardCategories) params.append("hazard", String(v));
  for (const v of f.productCategories) params.append("product", String(v));
  for (const v of f.countries) params.append("country", v);
  for (const v of f.risks) params.append("risk", v);
  if (f.from) params.set("from", f.from);
  if (f.to) params.set("to", f.to);
  if (f.officialOnly) params.set("official_only", "1");
  if (page > 1) params.set("page", String(page));
  return params;
}
