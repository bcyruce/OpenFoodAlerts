// Apache ECharts with only the parts the dashboard uses (tree-shaken `echarts/core`).
// Loaded with import() from <Chart>, so it never enters the server render or the
// first-paint bundle.
import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  SVGRenderer,
]);

export { echarts };
