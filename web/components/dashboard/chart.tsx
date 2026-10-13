"use client";

import { useEffect, useRef } from "react";
import type { ChartOption } from "./chart-types";

type Props = {
  option: ChartOption;
  /** Short description for screen readers; the data table next to the chart has the numbers. */
  label: string;
  height: number;
  testId?: string;
};

/**
 * One ECharts chart. The library is imported on the client after the first paint; the
 * server renders an empty box of the final height, so nothing shifts. Screen readers get
 * `label` (role="img") and the data table that every chart has next to it.
 */
export function Chart({ option, label, height, testId }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<import("echarts/core").EChartsType | null>(null);
  const latest = useRef(option);

  useEffect(() => {
    latest.current = option;
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | undefined;
    void import("./echarts").then(({ echarts }) => {
      if (disposed || !box.current) return;
      const instance = echarts.init(box.current, null, { renderer: "svg" });
      instance.setOption(latest.current, { notMerge: true });
      chart.current = instance;
      observer = new ResizeObserver(() => instance.resize());
      observer.observe(box.current);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  return (
    <div
      ref={box}
      role="img"
      aria-label={label}
      data-testid={testId}
      style={{ height }}
      className="w-full"
    />
  );
}
