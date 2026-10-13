/**
 * The dashboard's query: the shared filters (`filters.ts`, spec §8) plus a relative period.
 * Pure and safe for client components.
 *
 * `months`: the last N calendar months in Europe/Amsterdam, the current month included
 * (`months=12` on 25 October 2026 is 1 November 2025 onwards). It is the default period
 * (DEFAULT_MONTHS) when the URL sets none of `months`, `from` and `to`; `months=all` means
 * no lower bound. `from`/`to` take precedence: with either one set, `months` is ignored.
 */
import {
  parseFilters,
  toSearchParams,
  type Filters,
  type RawParams,
} from "./filters";

/** Values per dimension in the Top-N lists. */
export const TOP_N = 10;
/** Hazard category × origin country pairs in the heatmap, most Notifications first. */
export const HEATMAP_PAIRS = 20;

export type Dimension = "hazard" | "product" | "country";
export const DIMENSIONS: Dimension[] = ["hazard", "product", "country"];

export const DEFAULT_MONTHS = 12;
export const MAX_MONTHS = 240;
/** Periods offered by the dashboard; any other `months` value in the URL still works. */
export const MONTH_PRESETS = [3, 6, 12, 24, 60] as const;

export type StatsQuery = {
  filters: Filters;
  /** Last N months (current month included); null: `from`/`to` or all time. */
  months: number | null;
};

function first(params: RawParams, name: string): string | undefined {
  if (params instanceof URLSearchParams) return params.get(name) ?? undefined;
  const v = params[name];
  return Array.isArray(v) ? v[0] : v;
}

export function parseStatsQuery(params: RawParams): StatsQuery {
  const filters = parseFilters(params);
  if (filters.from || filters.to) return { filters, months: null };
  const raw = first(params, "months")?.trim().toLowerCase();
  if (raw === "all") return { filters, months: null };
  const n = Number(raw);
  const months =
    raw && /^\d+$/.test(raw) && n >= 1 ? Math.min(n, MAX_MONTHS) : DEFAULT_MONTHS;
  return { filters, months };
}

/** Canonical URL parameters: the shared filters, then `months` unless it is the default. */
export function toStatsParams(query: StatsQuery): URLSearchParams {
  const params = toSearchParams({ q: "", page: 1, filters: query.filters });
  const f = query.filters;
  if (query.months === null) {
    if (!f.from && !f.to) params.set("months", "all");
  } else if (query.months !== DEFAULT_MONTHS) {
    params.set("months", String(query.months));
  }
  return params;
}

const AMSTERDAM_MONTH = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Amsterdam",
  year: "numeric",
  month: "2-digit",
});

/** The calendar month (YYYY-MM) of `date` in Europe/Amsterdam. */
export function amsterdamMonth(date: Date): string {
  const parts = AMSTERDAM_MONTH.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}`;
}

/** `month` (YYYY-MM) shifted by `delta` months. */
export function addMonths(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** Every month from `first` to `last` (YYYY-MM), both included; empty if first > last. */
export function monthRange(first: string, last: string): string[] {
  const out: string[] = [];
  for (let m = first; m <= last; m = addMonths(m, 1)) out.push(m);
  return out;
}

/** The filters with a relative period turned into `from` (first day of the first month). */
export function resolvePeriod(query: StatsQuery, now: Date): Filters {
  if (query.months === null) return query.filters;
  const from = `${addMonths(amsterdamMonth(now), -(query.months - 1))}-01`;
  return { ...query.filters, from, to: null };
}
