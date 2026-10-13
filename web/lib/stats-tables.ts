/**
 * Chart data from a StatsResponse, as the dashboard's data tables and ECharts series need
 * it. Pure and client-safe (type imports only), so the server-rendered tables and the
 * client-side charts come from the same numbers.
 */
import type { HeatmapRow, StatsResponse } from "./stats";

export type TimeSeriesTable = {
  /** Source labels, in response order. */
  columns: string[];
  /** One row per month, oldest first; `counts` aligned with `columns`. */
  rows: { month: string; counts: number[] }[];
  totals: number[];
};

export function timeSeriesTable(stats: StatsResponse): TimeSeriesTable {
  return {
    columns: stats.sources.map((s) => s.label),
    rows: stats.months.map((month, i) => ({
      month,
      counts: stats.sources.map((s) => s.monthly[i] ?? 0),
    })),
    totals: stats.sources.map((s) => s.total),
  };
}

export function pairLabel(row: HeatmapRow): string {
  return `${row.hazard.label} · ${row.country.label}`;
}

export type HeatmapGrid = {
  /** Pair labels bottom to top (ECharts category order); the largest pair is last. */
  yLabels: string[];
  /** [month index, pair index, count], non-zero cells only. */
  cells: [number, number, number][];
  max: number;
};

/** The heatmap rows (largest first) as ECharts heatmap data. */
export function heatmapGrid(rows: HeatmapRow[]): HeatmapGrid {
  const n = rows.length;
  const cells: [number, number, number][] = [];
  let max = 0;
  rows.forEach((row, i) => {
    row.counts.forEach((count, x) => {
      if (count > 0) cells.push([x, n - 1 - i, count]);
      max = Math.max(max, count);
    });
  });
  return { yLabels: rows.map(pairLabel).reverse(), cells, max };
}

const INTL_LOCALE: Record<string, string> = { en: "en-GB", nl: "nl-NL" };

/** "2026-10" → "Oct 2026" (en) / "okt 2026" (nl). */
export function formatMonth(locale: string, month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(INTL_LOCALE[locale] ?? locale, {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  })
    .format(new Date(Date.UTC(y, m - 1, 1)))
    .replace(".", "");
}
