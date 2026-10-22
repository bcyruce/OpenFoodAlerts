import { describe, expect, it } from "vitest";
import type { HeatmapRow, StatsResponse } from "./stats";
import { formatMonth, heatmapGrid, pairLabel, timeSeriesTable } from "./stats-tables";
import { NO_FILTERS } from "./filters";

const empty = { hazard: 0, product: 0, country: 0 };
const noTop = { hazard: [], product: [], country: [] };

const RESPONSE: StatsResponse = {
  filters: NO_FILTERS,
  period: { months: 3, from: "2026-08-01", to: null },
  months: ["2026-08", "2026-09", "2026-10"],
  sources: [
    { source: "rasff", label: "RASFF", total: 5, classified: empty, classifiedAi: empty, monthly: [0, 2, 3], top: noTop, heatmap: [] },
    { source: "nvwa", label: "NVWA", total: 2, classified: empty, classifiedAi: empty, monthly: [1, 0, 1], top: noTop, heatmap: [] },
  ],
};

const PEST_IN: HeatmapRow = {
  hazard: { value: "21795", label: "pesticide residues" },
  country: { value: "IN", label: "India" },
  total: 3,
  counts: [0, 1, 2],
};
const PATH_BR: HeatmapRow = {
  hazard: { value: "21801", label: "pathogenic micro-organisms" },
  country: { value: "BR", label: "Brazil" },
  total: 1,
  counts: [1, 0, 0],
};

describe("timeSeriesTable", () => {
  it("has one row per month and one column per Source", () => {
    expect(timeSeriesTable(RESPONSE)).toEqual({
      columns: ["RASFF", "NVWA"],
      rows: [
        { month: "2026-08", counts: [0, 1] },
        { month: "2026-09", counts: [2, 0] },
        { month: "2026-10", counts: [3, 1] },
      ],
      totals: [5, 2],
    });
  });
});

describe("heatmapGrid", () => {
  it("puts the largest pair on top and leaves empty cells out", () => {
    // ECharts draws the first y category at the bottom.
    expect(heatmapGrid([PEST_IN, PATH_BR])).toEqual({
      yLabels: ["pathogenic micro-organisms · Brazil", "pesticide residues · India"],
      cells: [
        [1, 1, 1],
        [2, 1, 2],
        [0, 0, 1],
      ],
      max: 2,
    });
  });

  it("is empty without pairs", () => {
    expect(heatmapGrid([])).toEqual({ yLabels: [], cells: [], max: 0 });
  });
});

describe("labels", () => {
  it("names a pair and a month", () => {
    expect(pairLabel(PEST_IN)).toBe("pesticide residues · India");
    expect(formatMonth("en", "2026-10")).toBe("Oct 2026");
    expect(formatMonth("nl", "2026-10")).toBe("okt 2026");
  });
});
