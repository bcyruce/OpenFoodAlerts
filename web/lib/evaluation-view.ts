/**
 * What `/en/evaluation` shows, derived from a parsed latest.json (`lib/evaluation.ts`).
 * Pure: the page, its charts and its data tables all read these values, so a chart and
 * its table cannot disagree.
 */
import {
  SOURCES,
  TASKS,
  type ClassificationBlock,
  type ClassificationRun,
  type Confidence,
  type EvalReport,
  type EvalRun,
  type EvalSource,
  type EvalTask,
  type Interval,
  type SpanBlock,
  type Threshold,
} from "./evaluation";

export const SOURCE_LABELS: Record<EvalSource, string> = {
  rasff: "RASFF (subject only)",
  nvwa: "NVWA",
  openfda: "openFDA",
};

export const TASK_LABELS: Record<EvalTask, string> = {
  hazard_category: "T1 Hazard category",
  product_category: "T2 Product category",
  hazard: "T3 Hazard (text span)",
  origin_country: "T4 Country of origin",
  product_type: "T5 Product type",
};

export const SPLIT_ORDER = ["test", "dev"];

export type Scope = "overall" | EvalSource;

export type SplitSection = {
  split: string;
  items: number;
  labelled: number;
  tasks: { task: EvalTask; runs: EvalRun[] }[];
};

/** Models first, then baselines; by name within each. */
function byKindThenName(a: EvalRun, b: EvalRun): number {
  return (
    Number(a.kind === "baseline") - Number(b.kind === "baseline") ||
    a.model.localeCompare(b.model) ||
    a.prompt_version.localeCompare(b.prompt_version)
  );
}

/** The splits that have runs: test (frozen, the headline) first, then dev. */
export function splitSections(report: EvalReport): SplitSection[] {
  const splits = [...new Set(report.runs.map((r) => r.split))].sort(
    (a, b) => rank(a) - rank(b) || a.localeCompare(b),
  );
  return splits.map((split) => {
    const runs = report.runs.filter((r) => r.split === split);
    return {
      split,
      items: report.label_status[split]?.items ?? 0,
      labelled: report.label_status[split]?.labelled ?? 0,
      tasks: TASKS.filter((t) => runs.some((r) => r.task === t)).map((task) => ({
        task,
        runs: runs.filter((r) => r.task === task).sort(byKindThenName),
      })),
    };
  });
}

function rank(split: string): number {
  const i = SPLIT_ORDER.indexOf(split);
  return i === -1 ? SPLIT_ORDER.length : i;
}

export type MetricRow<B> = { scope: Scope; label: string; block: B };

/** The overall value first, then one row per Source the task is scored on. */
export function metricRows(run: ClassificationRun): MetricRow<ClassificationBlock>[];
export function metricRows(run: EvalRun): MetricRow<ClassificationBlock | SpanBlock>[];
export function metricRows(run: EvalRun): MetricRow<ClassificationBlock | SpanBlock>[] {
  const rows: MetricRow<ClassificationBlock | SpanBlock>[] = [
    { scope: "overall", label: "All sources", block: run.overall },
  ];
  for (const source of SOURCES) {
    const block = run.by_source[source];
    if (block) rows.push({ scope: source, label: SOURCE_LABELS[source], block });
  }
  return rows;
}

export type ComparisonRow = {
  model: string;
  prompt_version: string;
  kind: "model" | "baseline";
  overall: ClassificationRun["overall"];
  bySource: ClassificationRun["by_source"];
};

/** Every model and baseline on T1 for one split. */
export function comparisonRows(report: EvalReport, split: string): ComparisonRow[] {
  return report.runs
    .filter((r): r is ClassificationRun => r.split === split && r.task === "hazard_category" && r.family === "classification")
    .sort(byKindThenName)
    .map((r) => ({
      model: r.model,
      prompt_version: r.prompt_version,
      kind: r.kind,
      overall: r.overall,
      bySource: r.by_source,
    }));
}

export type CoverageChart = {
  series: { scope: Scope; label: string; points: ClassificationBlock["coverage_accuracy"] }[];
  /** The point of the overall curve at the chosen threshold, or null when none is chosen. */
  threshold: { min_confidence: Confidence; coverage: number | null; accuracy: number | null } | null;
};

export function coverageSeries(run: ClassificationRun, thresholds: Threshold[]): CoverageChart {
  const chosen = thresholds.find(
    (t) => t.model === run.model && t.prompt_version === run.prompt_version && t.task === run.task,
  );
  const point = chosen && run.overall.coverage_accuracy.find((p) => p.min_confidence === chosen.min_confidence);
  return {
    series: metricRows(run).map((row) => ({
      scope: row.scope,
      label: row.label,
      points: row.block.coverage_accuracy,
    })),
    threshold: chosen
      ? { min_confidence: chosen.min_confidence, coverage: point?.coverage ?? null, accuracy: point?.accuracy ?? null }
      : null,
  };
}

export type ConfusionTable = {
  /** Labels (rows) and model outputs (columns) that occur at least once. */
  rows: string[];
  columns: string[];
  cells: number[][];
  /** Labels that occur in neither, left out of the table. */
  hidden: string[];
};

export function confusionTable(run: ClassificationRun): ConfusionTable {
  const { labels, matrix } = run.confusion_matrix;
  const rowSum = (i: number) => matrix[i].reduce((a, b) => a + b, 0);
  const colSum = (j: number) => matrix.reduce((a, row) => a + row[j], 0);
  const rowIdx = labels.map((_, i) => i).filter((i) => rowSum(i) > 0);
  const colIdx = labels.map((_, j) => j).filter((j) => colSum(j) > 0 || rowSum(j) > 0);
  return {
    rows: rowIdx.map((i) => labels[i]),
    columns: colIdx.map((j) => labels[j]),
    cells: rowIdx.map((i) => colIdx.map((j) => matrix[i][j])),
    hidden: labels.filter((_, k) => rowSum(k) === 0 && colSum(k) === 0),
  };
}

export const NOT_DEFINED = "—";

export function formatRate(value: number | null): string {
  return value === null ? NOT_DEFINED : value.toFixed(2);
}

export function formatInterval(value: Interval | null): string {
  return value === null ? NOT_DEFINED : `${value[0].toFixed(2)}–${value[1].toFixed(2)}`;
}

/** "0.74 (0.68–0.80)": a value with its 95% CI. */
export function formatWithInterval(value: number | null, ci: Interval | null): string {
  return value === null ? NOT_DEFINED : ci === null ? formatRate(value) : `${formatRate(value)} (${formatInterval(ci)})`;
}

export function formatPercent(value: number | null): string {
  return value === null ? NOT_DEFINED : `${(value * 100).toFixed(1)}%`;
}
