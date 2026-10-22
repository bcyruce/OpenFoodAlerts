// The test-set number an AI badge quotes (spec §9), read from the real eval reports:
// example.json is synthetic (numbers copied from the file), latest.json has no runs yet.
import { describe, expect, it } from "vitest";
import { testAccuracy } from "./ai-badge";
import { EVAL_EXAMPLE_FILE, EVAL_RESULTS_FILE, loadEvalReport } from "./evaluation";

const example = loadEvalReport(EVAL_EXAMPLE_FILE);

describe("testAccuracy", () => {
  it("quotes the test-split accuracy of that model and prompt version", () => {
    const run = { model: "synthetic-model", promptVersion: "v0" };
    expect(testAccuracy(example, { ...run, task: "hazard_category" })).toBe(0.7397959183673469);
    expect(testAccuracy(example, { ...run, task: "product_category" })).toBe(0.75);
  });

  it("quotes exact match for the span tasks", () => {
    const run = { model: "synthetic-model", promptVersion: "v0" };
    expect(testAccuracy(example, { ...run, task: "origin_country" })).toBe(0.81875);
    expect(testAccuracy(example, { ...run, task: "hazard" })).toBe(0.475);
  });

  it("has no number for another prompt version, another model, T6 or an empty report", () => {
    expect(
      testAccuracy(example, { model: "synthetic-model", promptVersion: "v1", task: "hazard_category" }),
    ).toBeNull();
    expect(
      testAccuracy(example, { model: "claude-haiku-5-5", promptVersion: "v0", task: "hazard_category" }),
    ).toBeNull();
    expect(
      testAccuracy(example, { model: "synthetic-model", promptVersion: "v0", task: "summary_en" }),
    ).toBeNull();
    const latest = loadEvalReport(EVAL_RESULTS_FILE);
    expect(
      testAccuracy(latest, { model: "claude-haiku-5-5", promptVersion: "v1", task: "hazard_category" }),
    ).toBeNull();
  });

  it("has no number when the test run had no Labels (n = 0)", () => {
    const empty = structuredClone(example);
    const run = empty.runs.find((r) => r.split === "test" && r.task === "hazard_category")!;
    if (run.family === "classification") run.overall.accuracy = null;
    expect(
      testAccuracy(empty, { model: "synthetic-model", promptVersion: "v0", task: "hazard_category" }),
    ).toBeNull();
  });
});
