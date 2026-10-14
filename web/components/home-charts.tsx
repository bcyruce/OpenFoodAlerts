"use client";

import { useMemo } from "react";
import type { StatsResponse, TopItem } from "@/lib/stats";
import { Chart } from "./dashboard/chart";
import { timeSeriesOption, topHeight, topOption } from "./dashboard/options";

// Chart thumbnails for the home page, from the dashboard's chart options. Built on the
// client because ECharts options contain functions; the data tables are server-rendered.

export function TimeSeriesThumbnail({
  stats,
  locale,
  label,
}: {
  stats: StatsResponse;
  locale: string;
  label: string;
}) {
  const option = useMemo(() => timeSeriesOption(stats, locale), [stats, locale]);
  return <Chart option={option} label={label} height={240} testId="home-chart-timeseries" />;
}

export function TopThumbnail({
  items,
  color,
  locale,
  label,
}: {
  items: TopItem[];
  color: string;
  locale: string;
  label: string;
}) {
  const option = useMemo(() => topOption(items, color, locale), [items, color, locale]);
  return <Chart option={option} label={label} height={topHeight(items.length)} testId="home-chart-top" />;
}
