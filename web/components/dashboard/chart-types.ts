import type { BarSeriesOption, HeatmapSeriesOption, LineSeriesOption } from "echarts/charts";
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from "echarts/components";
import type { ComposeOption } from "echarts/core";

/** The ECharts option type for the components registered in `echarts.ts`. */
export type ChartOption = ComposeOption<
  | BarSeriesOption
  | HeatmapSeriesOption
  | LineSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
  | VisualMapComponentOption
>;
