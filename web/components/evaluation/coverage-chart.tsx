"use client";

import { useMemo } from "react";
import { Chart } from "@/components/dashboard/chart";
import type { ChartOption } from "@/components/dashboard/chart-types";
import { SOURCE_COLORS } from "@/components/dashboard/options";
import type { CoverageChart as CoverageData, Scope } from "@/lib/evaluation-view";

// The coverage–accuracy curve of one run (spec §7.2): one point per confidence level
// ("answer only when confidence ≥ level"), one line per Source plus all Sources, and the
// chosen low-confidence threshold (ticket 21) as a marked point when there is one. Built
// on the client because ECharts options contain functions; the data table is
// server-rendered next to it.

const COLORS: Record<Scope, string> = { overall: "#0f172a", ...SOURCE_COLORS };
const INK = "#334155"; // slate-700
const GRID_LINE = "#e2e8f0";
const MUTED_LINE = "#cbd5e1";
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const axisText = { color: INK, fontFamily: FONT, fontSize: 12 };
const percent = (v: number) => `${Math.round(v * 100)}%`;

function coverageOption(chart: CoverageData): ChartOption {
  const lines = chart.series.map((s) => ({
    type: "line" as const,
    name: s.label,
    color: COLORS[s.scope],
    lineStyle: { width: s.scope === "overall" ? 3 : 2 },
    symbol: "circle",
    symbolSize: 8,
    data: s.points
      .filter((p) => p.coverage !== null && p.accuracy !== null)
      .map((p) => ({ value: [p.coverage as number, p.accuracy as number], name: p.min_confidence })),
  }));
  const t = chart.threshold;
  const marker =
    t && t.coverage !== null && t.accuracy !== null
      ? [
          {
            type: "line" as const,
            name: `Chosen threshold (≥ ${t.min_confidence})`,
            color: "#7c2d12",
            symbol: "diamond",
            symbolSize: 18,
            z: 10,
            data: [{ value: [t.coverage, t.accuracy], name: t.min_confidence }],
            label: { show: true, position: "top" as const, formatter: "threshold", color: "#7c2d12", fontFamily: FONT },
          },
        ]
      : [];
  return {
    animation: false,
    textStyle: { fontFamily: FONT },
    grid: { left: 8, right: 24, top: 48, bottom: 28, containLabel: true },
    legend: { top: 0, left: 0, textStyle: axisText, icon: "roundRect" },
    tooltip: {
      trigger: "item",
      confine: true,
      textStyle: { color: "#0f172a", fontFamily: FONT, fontSize: 13 },
      borderColor: MUTED_LINE,
      formatter: (p) => {
        const item = p as unknown as { seriesName: string; name: string; value: [number, number] };
        return `${item.seriesName}<br>confidence ≥ ${item.name}<br>coverage ${percent(item.value[0])}, accuracy ${percent(item.value[1])}`;
      },
    },
    xAxis: {
      type: "value",
      min: 0,
      max: 1,
      name: "Coverage (share of items answered)",
      nameLocation: "middle",
      nameGap: 28,
      nameTextStyle: axisText,
      axisLabel: { ...axisText, formatter: percent },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      name: "Accuracy of the answers",
      nameTextStyle: { ...axisText, align: "left" },
      axisLabel: { ...axisText, formatter: percent },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series: [...lines, ...marker],
  };
}

export function CoverageChart({ chart, label, testId }: { chart: CoverageData; label: string; testId?: string }) {
  const option = useMemo(() => coverageOption(chart), [chart]);
  return <Chart option={option} label={label} height={300} testId={testId} />;
}
