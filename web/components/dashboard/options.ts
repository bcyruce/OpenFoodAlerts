// ECharts options for the dashboard charts, built from the same StatsResponse as the data
// tables. Colours: one fixed hue per Source (it follows the Source, never its rank) and a
// one-hue blue ramp for the heatmap; text stays in the site's slate ink (AA on white).
import type { FilterSource } from "@/lib/filters";
import type { HeatmapRow, StatsResponse, TopItem } from "@/lib/stats";
import { formatMonth, heatmapGrid } from "@/lib/stats-tables";
import type { ChartOption } from "./chart-types";

export const SOURCE_COLORS: Record<FilterSource, string> = {
  rasff: "#2a78d6",
  nvwa: "#eb6834",
  openfda: "#1baf7a",
};

/** Sequential ramp, light (few) to dark (many). */
const RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const INK = "#334155"; // slate-700
const MUTED_LINE = "#cbd5e1"; // slate-300
const GRID_LINE = "#e2e8f0"; // slate-200
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

const axisText = { color: INK, fontFamily: FONT, fontSize: 12 };
const tooltipBase = {
  confine: true,
  textStyle: { color: "#0f172a", fontFamily: FONT, fontSize: 13 },
  borderColor: MUTED_LINE,
};

export function timeSeriesOption(stats: StatsResponse, locale: string): ChartOption {
  const months = stats.months.map((m) => formatMonth(locale, m));
  const several = stats.sources.length > 1;
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: { left: 8, right: several ? 72 : 16, top: several ? 36 : 16, bottom: 8, containLabel: true },
    legend: several ? { top: 0, left: 0, textStyle: axisText, icon: "roundRect" } : undefined,
    tooltip: { ...tooltipBase, trigger: "axis" },
    xAxis: {
      type: "category",
      data: months,
      boundaryGap: false,
      axisLabel: axisText,
      axisLine: { lineStyle: { color: MUTED_LINE } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: axisText,
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series: stats.sources.map((s) => ({
      type: "line",
      name: s.label,
      data: s.monthly,
      color: SOURCE_COLORS[s.source],
      lineStyle: { width: 2 },
      symbol: "circle",
      symbolSize: 8,
      showSymbol: stats.months.length <= 24,
      endLabel: several ? { show: true, formatter: s.label, color: INK, fontFamily: FONT } : undefined,
    })),
  };
}

export function heatmapOption(rows: HeatmapRow[], monthKeys: string[], locale: string): ChartOption {
  const grid = heatmapGrid(rows);
  const number = new Intl.NumberFormat(locale);
  const months = monthKeys.map((m) => formatMonth(locale, m));
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: { left: 8, right: 16, top: 8, bottom: 48, containLabel: true },
    tooltip: {
      ...tooltipBase,
      formatter: (p) => {
        const [x, y, count] = (p as unknown as { value: [number, number, number] }).value;
        return `${grid.yLabels[y]}<br>${months[x]}: <b>${number.format(count)}</b>`;
      },
    },
    xAxis: {
      type: "category",
      data: months,
      axisLabel: axisText,
      axisLine: { lineStyle: { color: MUTED_LINE } },
      axisTick: { show: false },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: grid.yLabels,
      axisLabel: { ...axisText, width: 220, overflow: "truncate" },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      type: "continuous",
      // From 0, so that a single Notification is clearly darker than the empty surface.
      min: 0,
      max: Math.max(grid.max, 1),
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemHeight: 160,
      itemWidth: 12,
      inRange: { color: RAMP },
      textStyle: axisText,
    },
    series: [
      {
        type: "heatmap",
        data: grid.cells,
        // A 2px surface gap between cells.
        itemStyle: { borderColor: "#ffffff", borderWidth: 2, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: "#0f172a", borderWidth: 1 } },
      },
    ],
  };
}

export function heatmapHeight(rows: number): number {
  return 90 + rows * 26;
}

export function topOption(items: TopItem[], color: string, locale: string): ChartOption {
  const number = new Intl.NumberFormat(locale);
  const shown = [...items].reverse(); // ECharts draws the first category at the bottom.
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: { left: 8, right: 48, top: 4, bottom: 4, containLabel: true },
    tooltip: { ...tooltipBase, trigger: "item" },
    xAxis: { type: "value", show: false, minInterval: 1 },
    yAxis: {
      type: "category",
      data: shown.map((i) => i.label),
      axisLabel: { ...axisText, width: 260, overflow: "truncate" },
      axisLine: { lineStyle: { color: MUTED_LINE } },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        data: shown.map((i) => i.count),
        color,
        barMaxWidth: 16,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: "right",
          color: INK,
          fontFamily: FONT,
          formatter: (p) => number.format(Number(p.value)),
        },
      },
    ],
  };
}

export function topHeight(items: number): number {
  return 24 + items * 26;
}
