import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { REPO_ROOT } from "./repo";
import {
  EVAL_EXAMPLE_FILE,
  EVAL_LABELS_FILE,
  EVAL_RESULTS_FILE,
  loadEvalReport,
  parseEvalReport,
  readGuidelineVersions,
} from "./evaluation";

describe("readGuidelineVersions", () => {
  it("is empty for the committed labels.csv (header only)", () => {
    expect(readGuidelineVersions(EVAL_LABELS_FILE)).toEqual({ A: [], B: [] });
  });

  it("lists the guideline versions each annotator used, oldest first", () => {
    const file = path.join(mkdtempSync(path.join(tmpdir(), "ofa-labels-")), "labels.csv");
    writeFileSync(
      file,
      "item_id,annotator,guideline_version,hazard_category,product_category,hazard,origin_country,product_type,note,labelled_at\n" +
        'nv-1,A,v10,allergens,unsure,none,unknown,food,"milk, not declared",2026-10-26T08:00:00Z\n' +
        "nv-1,A,v2,allergens,unsure,none,unknown,food,,2026-10-26T08:00:00Z\n" +
        "nv-2,A,v2,allergens,unsure,none,unknown,food,,2026-10-26T08:00:00Z\n" +
        "nv-2,B,v2,allergens,unsure,none,unknown,food,,2026-10-26T08:00:00Z\n",
    );
    expect(readGuidelineVersions(file)).toEqual({ A: ["v2", "v10"], B: ["v2"] });
  });
});

// The loader of eval/results/latest.json (ticket 15's harness output, spec §7.3). Checked
// against the committed real file (no Labels yet) and the synthetic example.

const minimal = {
  git_sha: "abc",
  created_at: "2026-10-25T05:08:40+00:00",
  taxonomy_version: 1,
  synthetic: false,
  bootstrap: { resamples: 1000, seed: 20261025, level: 0.95 },
  label_status: { test: { items: 200, labelled: 0 } },
  runs: [],
  skipped: [],
  agreement: { cohens_kappa: null, n: 0, task: "hazard_category", subset_size: 60, by_task: {} },
  noise_audit: { agreement_with_official: null, n: 0, n_unsure: 0, n_unmapped: 0, n_multi_label: 0 },
};

const emptyBlock = {
  n: 0,
  accuracy: null,
  accuracy_ci95: null,
  accuracy_answered: null,
  macro_f1: null,
  macro_f1_ci95: null,
  weighted_f1: null,
  abstention_rate: null,
  coverage_accuracy: [
    { min_confidence: "high", coverage: null, accuracy: null, n: 0 },
    { min_confidence: "medium", coverage: null, accuracy: null, n: 0 },
    { min_confidence: "low", coverage: null, accuracy: null, n: 0 },
  ],
  n_missing: 0,
  n_stale: 0,
};

describe("loadEvalReport", () => {
  it("reads the committed latest.json: no Labels yet, so no runs", () => {
    expect(path.relative(REPO_ROOT, EVAL_RESULTS_FILE).split(path.sep).join("/")).toBe(
      "eval/results/latest.json",
    );
    const report = loadEvalReport(EVAL_RESULTS_FILE);
    expect(report.synthetic).toBe(false);
    expect(report.taxonomy_version).toBe("v1-draft");
    expect(report.runs).toEqual([]);
    expect(report.label_status.test).toEqual({ items: 200, labelled: 0 });
    expect(report.skipped).toContainEqual({
      model: "baseline-keywords",
      prompt_version: "kw1",
      split: "test",
      task: "hazard_category",
      reason: "no Labels",
    });
    expect(report.agreement.cohens_kappa).toBeNull();
    expect(report.noise_audit.agreement_with_official).toBeNull();
    expect(report.thresholds).toEqual([]);
  });

  it("reads the synthetic example with every task, baselines, κ and the noise audit", () => {
    const report = loadEvalReport(EVAL_EXAMPLE_FILE);
    expect(report.synthetic).toBe(true);
    expect(report.runs).toHaveLength(14);
    const t1 = report.runs.find(
      (r) => r.model === "synthetic-model" && r.split === "test" && r.task === "hazard_category",
    );
    expect(t1?.family).toBe("classification");
    if (t1?.family !== "classification") throw new Error("expected a classification run");
    expect(Object.keys(t1.by_source).sort()).toEqual(["nvwa", "openfda", "rasff"]);
    expect(t1.overall.n).toBe(196);
    expect(t1.overall.macro_f1).toBeCloseTo(0.64808, 4);
    expect(t1.overall.macro_f1_ci95?.[0]).toBeCloseTo(0.53468, 4);
    expect(t1.overall.coverage_accuracy.map((p) => p.min_confidence)).toEqual(["high", "medium", "low"]);
    expect(t1.confusion_matrix.labels.at(-1)).toBe("abstain");
    expect(t1.confusion_matrix.matrix).toHaveLength(27);
    expect(t1.per_class.allergens.support).toBeGreaterThan(0);

    const t3 = report.runs.find((r) => r.split === "test" && r.task === "hazard");
    expect(t3?.family).toBe("span");
    if (t3?.family !== "span") throw new Error("expected a span run");
    expect(t3.overall.exact_match).toBe(0.475);
    expect(t3.overall.normalized_match_ci95).toEqual([0.625, 0.76875]);

    expect(report.runs.filter((r) => r.kind === "baseline").map((r) => r.model)).toContain("baseline-tfidf-lr");
    expect(report.agreement.by_task.product_category.cohens_kappa).toBeCloseTo(0.578, 3);
    expect(report.noise_audit.n).toBe(60);
  });
});

describe("parseEvalReport", () => {
  it("accepts the frozen taxonomy version as the integer 1", () => {
    expect(parseEvalReport(minimal).taxonomy_version).toBe(1);
  });

  it("accepts the nulls of a block with n = 0", () => {
    const run = {
      model: "m",
      prompt_version: "v1",
      kind: "model",
      split: "dev",
      task: "product_type",
      schema_version: "1",
      taxonomy_version: 1,
      by_source: { nvwa: emptyBlock },
      overall: { ...emptyBlock, n_unsure: 0, n_unlabelled: 0 },
      per_class: {},
      confusion_matrix: { labels: ["abstain"], matrix: [[0]] },
    };
    const report = parseEvalReport({ ...minimal, runs: [run] });
    expect(report.runs[0].family).toBe("classification");
    expect(report.runs[0].by_source.nvwa?.n).toBe(0);
  });

  it("reads the low-confidence thresholds when the file has them (ticket 21)", () => {
    const thresholds = [
      { model: "m", prompt_version: "v1", task: "hazard_category", min_confidence: "medium" },
    ];
    expect(parseEvalReport({ ...minimal, thresholds }).thresholds).toEqual(thresholds);
  });

  it("names the broken field of a malformed file", () => {
    expect(() => parseEvalReport({ ...minimal, runs: undefined })).toThrow(/runs/);
    expect(() => parseEvalReport({ ...minimal, taxonomy_version: 2.5 })).toThrow(/taxonomy_version/);
    expect(() =>
      parseEvalReport({ ...minimal, noise_audit: { ...minimal.noise_audit, n: "60" } }),
    ).toThrow(/noise_audit\.n/);
    const badMatrix = {
      model: "m",
      prompt_version: "v1",
      kind: "model",
      split: "dev",
      task: "product_type",
      schema_version: "1",
      taxonomy_version: 1,
      by_source: {},
      overall: { ...emptyBlock, n_unsure: 0, n_unlabelled: 0 },
      per_class: {},
      confusion_matrix: { labels: ["food", "abstain"], matrix: [[0, 0]] },
    };
    expect(() => parseEvalReport({ ...minimal, runs: [badMatrix] })).toThrow(/runs\[0\]\.confusion_matrix/);
  });
});
