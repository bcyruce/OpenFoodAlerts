import { describe, expect, it } from "vitest";
import { EVAL_EXAMPLE_FILE, EVAL_RESULTS_FILE, loadEvalReport, type ClassificationRun } from "./evaluation";
import {
  comparisonRows,
  confusionTable,
  coverageSeries,
  formatInterval,
  formatRate,
  metricRows,
  splitSections,
} from "./evaluation-view";

// What /en/evaluation shows, derived from latest.json. Expected values are read off the
// committed example.json (synthetic) by hand.

const example = loadEvalReport(EVAL_EXAMPLE_FILE);
const t1 = example.runs.find(
  (r): r is ClassificationRun =>
    r.model === "synthetic-model" && r.split === "test" && r.task === "hazard_category",
)!;

describe("splitSections", () => {
  it("puts the frozen test split first, tasks in spec order, models before baselines", () => {
    const sections = splitSections(example);
    expect(sections.map((s) => s.split)).toEqual(["test", "dev"]);
    expect(sections[0].items).toBe(200);
    expect(sections[0].labelled).toBe(200);
    expect(sections[0].tasks.map((t) => t.task)).toEqual([
      "hazard_category",
      "product_category",
      "hazard",
      "origin_country",
      "product_type",
    ]);
    expect(sections[0].tasks[0].runs.map((r) => r.model)).toEqual([
      "synthetic-model",
      "baseline-keywords",
      "baseline-tfidf-lr",
    ]);
  });

  it("is empty while nothing is labelled", () => {
    expect(splitSections(loadEvalReport(EVAL_RESULTS_FILE))).toEqual([]);
  });
});

describe("metricRows", () => {
  it("gives the overall value first, then each Source (RASFF, NVWA, openFDA)", () => {
    const rows = metricRows(t1);
    expect(rows.map((r) => [r.scope, r.label, r.block.n])).toEqual([
      ["overall", "All sources", 196],
      ["rasff", "RASFF (subject only)", 40],
      ["nvwa", "NVWA", 79],
      ["openfda", "openFDA", 77],
    ]);
  });
});

describe("comparisonRows", () => {
  it("compares every model and baseline on T1 for one split", () => {
    const rows = comparisonRows(example, "test");
    expect(rows.map((r) => [r.model, r.kind])).toEqual([
      ["synthetic-model", "model"],
      ["baseline-keywords", "baseline"],
      ["baseline-tfidf-lr", "baseline"],
    ]);
    expect(rows[0].overall.macro_f1).toBeCloseTo(0.648, 3);
    expect(rows[0].bySource.rasff?.macro_f1).toBeCloseTo(0.4727, 4);
  });
});

describe("coverageSeries", () => {
  it("has one curve per scope and no threshold marker until one is chosen", () => {
    const chart = coverageSeries(t1, []);
    expect(chart.series.map((s) => s.scope)).toEqual(["overall", "rasff", "nvwa", "openfda"]);
    expect(chart.series[0].points.map((p) => [p.min_confidence, p.n])).toEqual([
      ["high", 110],
      ["medium", 151],
      ["low", 183],
    ]);
    expect(chart.threshold).toBeNull();
  });

  it("marks the threshold chosen for that model, prompt and task", () => {
    const thresholds = [
      { model: "synthetic-model", prompt_version: "v0", task: "hazard_category" as const, min_confidence: "medium" as const },
      { model: "other", prompt_version: "v0", task: "hazard_category" as const, min_confidence: "high" as const },
    ];
    const marked = coverageSeries(t1, thresholds).threshold;
    expect(marked?.min_confidence).toBe("medium");
    expect(marked?.coverage).toBeCloseTo(151 / 196, 6);
    expect(marked?.accuracy).toBeCloseTo(0.83444, 4);
  });
});

describe("confusionTable", () => {
  it("leaves out labels that are neither in the Labels nor in the outputs", () => {
    const run = {
      ...t1,
      confusion_matrix: {
        labels: ["allergens", "TSEs", "other", "abstain"],
        matrix: [
          [5, 0, 1, 2],
          [0, 0, 0, 0],
          [1, 0, 3, 0],
          [0, 0, 0, 0],
        ],
      },
    };
    expect(confusionTable(run)).toEqual({
      rows: ["allergens", "other"],
      columns: ["allergens", "other", "abstain"],
      cells: [
        [5, 1, 2],
        [1, 3, 0],
      ],
      hidden: ["TSEs"],
    });
  });

  it("keeps every label of the example's T1 run and all 196 items", () => {
    const table = confusionTable(t1);
    expect(table.hidden).toEqual([]);
    expect(table.cells.flat().reduce((a, b) => a + b, 0)).toBe(196);
  });
});

describe("formatting", () => {
  it("shows rates with two decimals, an en dash for intervals and a dash when undefined", () => {
    expect(formatRate(0.7397959)).toBe("0.74");
    expect(formatRate(null)).toBe("—");
    expect(formatInterval([0.67844, 0.80102])).toBe("0.68–0.80");
    expect(formatInterval(null)).toBe("—");
  });
});
