/**
 * Dashboard statistics (spec §8 `/api/stats`, §9 `/dashboard`), one block per Source.
 *
 * Scope: `scopeSql("stats")` (food, feed, food contact material; no RASFF News; spec §4.3)
 * and a publication date. Sources are never added up or deduplicated (ADR 0005). Counts
 * are Notifications: a Notification with two Hazards of one category counts once for
 * that category, one with two categories counts for each. Countries are origin countries
 * only. With `official_only`, AI classifications are left out of the filters and of every
 * dimension, but the Notifications themselves still count in `total` and `monthly`.
 */
import { sql, type SQL } from "drizzle-orm";
import { filtersSql, FROM_NOTIFICATIONS, provenanceSql, rows, scopeSql } from "./filter-sql";
import { SOURCES, type FilterSource, type Filters } from "./filters";
import type { Reader } from "./notifications";
import { categoryLabel, countryLabel, SOURCE_LABELS, type Names } from "./search";
import {
  amsterdamMonth,
  DIMENSIONS,
  HEATMAP_PAIRS,
  monthRange,
  resolvePeriod,
  TOP_N,
  type Dimension,
  type StatsQuery,
} from "./stats-query";

export { DIMENSIONS, HEATMAP_PAIRS, TOP_N, type Dimension };

/**
 * A Hazard category or Product category (RASFF id) or an origin country (ISO2). `ai`:
 * how many of the `count` Notifications have this value from an AI classification (always
 * 0 with official_only), so the dashboard can mark AI-derived numbers (spec §9).
 */
export type TopItem = { value: string; label: string; count: number; ai: number };

export type HeatmapRow = {
  hazard: { value: string; label: string };
  country: { value: string; label: string };
  /** Notifications with this Hazard category and origin country in the period. */
  total: number;
  /** Per month, aligned with `StatsResponse.months`. */
  counts: number[];
};

export type SourceStats = {
  source: FilterSource;
  label: string;
  total: number;
  /** Notifications with at least one value in each dimension (official only if so filtered). */
  classified: Record<Dimension, number>;
  /** Of `classified`, Notifications with a value from an AI classification. */
  classifiedAi: Record<Dimension, number>;
  /** Notifications per month, aligned with `StatsResponse.months`. */
  monthly: number[];
  /** Up to TOP_N values per dimension, most Notifications first. */
  top: Record<Dimension, TopItem[]>;
  /** Up to HEATMAP_PAIRS Hazard category × origin country pairs with monthly counts. */
  heatmap: HeatmapRow[];
};

export type StatsResponse = {
  filters: Filters;
  period: { months: number | null; from: string | null; to: string | null };
  /** Calendar months (YYYY-MM, Europe/Amsterdam), consecutive, oldest first. */
  months: string[];
  sources: SourceStats[];
};

const MONTH = sql`to_char(n.published_at AT TIME ZONE 'Europe/Amsterdam', 'YYYY-MM')`;

/** Notifications counted by the statistics: scope, filters and a publication date. */
function matchedSql(filters: Filters): SQL {
  return sql`SELECT n.id, s.code AS source, ${MONTH} AS month
    FROM ${FROM_NOTIFICATIONS}
    WHERE ${scopeSql("stats")} AND n.published_at IS NOT NULL AND ${filtersSql(filters)}`;
}

/** (notification id, value, names) for one dimension; `m` is the matched set. */
function valuesSql(dimension: Dimension, filters: Filters): SQL {
  switch (dimension) {
    case "hazard":
      return sql`SELECT h.notification_id AS id, d.rasff_id::text AS value, d.name_en, d.name_nl,
          h.provenance
        FROM notification_hazards h JOIN hazard_categories d ON d.id = h.hazard_category_id
        WHERE TRUE ${provenanceSql("h", filters)}`;
    case "product":
      return sql`SELECT pc.notification_id AS id, d.rasff_id::text AS value, d.name_en, d.name_nl,
          pc.provenance
        FROM notification_product_categories pc
        JOIN product_categories d ON d.id = pc.product_category_id
        WHERE TRUE ${provenanceSql("pc", filters)}`;
    case "country":
      return sql`SELECT c.notification_id AS id, d.iso2 AS value, d.name_en, d.name_nl,
          c.provenance
        FROM notification_countries c JOIN countries d ON d.iso2 = c.country_iso2
        WHERE c.role = 'origin' ${provenanceSql("c", filters)}`;
  }
}

/** `value` is null on the per-Source row: Notifications with any value (`classified`). */
type CountRow = Names & { source: string; value: string | null; count: number; ai: number };

async function countsBy(db: Reader, dimension: Dimension, filters: Filters): Promise<CountRow[]> {
  return rows<CountRow>(
    db,
    sql`SELECT m.source, v.value, v.name_en, v.name_nl, count(DISTINCT m.id)::int AS count,
          count(DISTINCT m.id) FILTER (WHERE v.provenance = 'ai')::int AS ai
        FROM (${matchedSql(filters)}) m JOIN (${valuesSql(dimension, filters)}) v ON v.id = m.id
        GROUP BY GROUPING SETS ((m.source, v.value, v.name_en, v.name_nl), (m.source))`,
  );
}

type CellRow = {
  source: string;
  hazard: string;
  hazard_en: string;
  hazard_nl: string | null;
  country: string;
  country_en: string;
  country_nl: string | null;
  month: string;
  count: number;
  total: number;
};

/** Monthly counts of the top Hazard category × origin country pairs of each Source. */
async function heatmapCells(db: Reader, filters: Filters): Promise<CellRow[]> {
  return rows<CellRow>(
    db,
    sql`WITH m AS (${matchedSql(filters)}),
      cells AS (
        SELECT m.source, h.value AS hazard, h.name_en AS hazard_en, h.name_nl AS hazard_nl,
               c.value AS country, c.name_en AS country_en, c.name_nl AS country_nl, m.month,
               count(DISTINCT m.id)::int AS count
        FROM m
        JOIN (${valuesSql("hazard", filters)}) h ON h.id = m.id
        JOIN (${valuesSql("country", filters)}) c ON c.id = m.id
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8),
      -- One month per Notification, so the monthly counts add up to the pair's total.
      pairs AS (
        SELECT source, hazard, country, sum(count)::int AS total,
               row_number() OVER (PARTITION BY source ORDER BY sum(count) DESC, hazard, country) AS rank
        FROM cells GROUP BY 1, 2, 3)
      SELECT cells.*, pairs.total FROM cells JOIN pairs USING (source, hazard, country)
      WHERE pairs.rank <= ${HEATMAP_PAIRS}`,
  );
}

function heatmapRows(
  cells: CellRow[],
  source: string,
  months: string[],
  locale: string,
  collator: Intl.Collator,
): HeatmapRow[] {
  const byPair = new Map<string, HeatmapRow>();
  for (const cell of cells) {
    if (cell.source !== source) continue;
    const key = `${cell.hazard}|${cell.country}`;
    let row = byPair.get(key);
    if (!row) {
      row = {
        hazard: {
          value: cell.hazard,
          label: categoryLabel(locale, { name_en: cell.hazard_en, name_nl: cell.hazard_nl }),
        },
        country: {
          value: cell.country,
          label: countryLabel(locale, cell.country, {
            name_en: cell.country_en,
            name_nl: cell.country_nl,
          }),
        },
        total: cell.total,
        counts: months.map(() => 0),
      };
      byPair.set(key, row);
    }
    const i = months.indexOf(cell.month);
    if (i >= 0) row.counts[i] = cell.count;
  }
  return [...byPair.values()].sort(
    (a, b) =>
      b.total - a.total ||
      collator.compare(a.hazard.label, b.hazard.label) ||
      collator.compare(a.country.label, b.country.label),
  );
}

function label(locale: string, dimension: Dimension, row: Names & { value: string }): string {
  return dimension === "country" ? countryLabel(locale, row.value, row) : categoryLabel(locale, row);
}

export async function getStats(
  db: Reader,
  query: StatsQuery,
  options: { locale: string; now?: Date },
): Promise<StatsResponse> {
  const { locale } = options;
  const now = options.now ?? new Date();
  const filters = resolvePeriod(query, now);
  const [perMonth, cells, ...byDimension] = await Promise.all([
    rows<{ source: string; month: string; count: number }>(
      db,
      sql`SELECT m.source, m.month, count(*)::int AS count FROM (${matchedSql(filters)}) m
          GROUP BY 1, 2`,
    ),
    heatmapCells(db, filters),
    ...DIMENSIONS.map((d) => countsBy(db, d, filters)),
  ]);
  const dataMonths = perMonth.map((r) => r.month).sort();
  const first = filters.from?.slice(0, 7) ?? dataMonths[0];
  const last = filters.to?.slice(0, 7) ?? [amsterdamMonth(now), ...dataMonths].sort().at(-1)!;
  const months = first ? monthRange(first, last) : [];
  const shown = filters.sources.length > 0 ? filters.sources : [...SOURCES];
  const collator = new Intl.Collator(locale);

  const top = (source: string, i: number): TopItem[] =>
    byDimension[i]
      .filter((r): r is CountRow & { value: string } => r.source === source && r.value !== null)
      .map((r) => ({
        value: r.value,
        label: label(locale, DIMENSIONS[i], r),
        count: r.count,
        ai: r.ai,
      }))
      .sort((a, b) => b.count - a.count || collator.compare(a.label, b.label))
      .slice(0, TOP_N);
  const perSource = (source: string, i: number) =>
    byDimension[i].find((r) => r.source === source && r.value === null);
  const classified = (source: string, i: number): number => perSource(source, i)?.count ?? 0;
  const classifiedAi = (source: string, i: number): number => perSource(source, i)?.ai ?? 0;

  return {
    filters,
    period: { months: query.months, from: filters.from, to: filters.to },
    months,
    sources: SOURCES.filter((s) => shown.includes(s)).map((source) => {
      const own = perMonth.filter((r) => r.source === source);
      return {
        source,
        label: SOURCE_LABELS[source],
        total: own.reduce((sum, r) => sum + r.count, 0),
        classified: {
          hazard: classified(source, 0),
          product: classified(source, 1),
          country: classified(source, 2),
        },
        classifiedAi: {
          hazard: classifiedAi(source, 0),
          product: classifiedAi(source, 1),
          country: classifiedAi(source, 2),
        },
        monthly: months.map((m) => own.find((r) => r.month === m)?.count ?? 0),
        top: {
          hazard: top(source, 0),
          product: top(source, 1),
          country: top(source, 2),
        },
        heatmap: heatmapRows(cells, source, months, locale, collator),
      };
    }),
  };
}
