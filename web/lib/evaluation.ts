/**
 * `eval/results/latest.json` (spec §7.3, extended by ticket 15's harness; field reference in
 * `eval/README.md`), read and checked at build time for `/en/evaluation`. Field names stay
 * as in the file. Hand-written guards: every error names the broken field
 * (`runs[3].overall.macro_f1`), so a harness change fails the build loudly instead of
 * rendering wrong numbers. Undefined values (n = 0) are `null`.
 *
 * Read with sync `fs`, so a page that shows it stays static (as `lib/taxonomy.ts`).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { REPO_ROOT } from "./repo";
import { parseCsv } from "./taxonomy";

export const EVAL_RESULTS_FILE = path.join(REPO_ROOT, "eval", "results", "latest.json");
/** Synthetic (`"synthetic": true`): invented Labels and model. Never the public page. */
export const EVAL_EXAMPLE_FILE = path.join(REPO_ROOT, "eval", "results", "example.json");
export const EVAL_LABELS_FILE = path.join(REPO_ROOT, "eval", "labels.csv");

export const SOURCES = ["rasff", "nvwa", "openfda"] as const;
export type EvalSource = (typeof SOURCES)[number];

export const CONFIDENCES = ["high", "medium", "low"] as const;
export type Confidence = (typeof CONFIDENCES)[number];

/** T1–T5 in spec order (§6.1). */
export const TASKS = ["hazard_category", "product_category", "hazard", "origin_country", "product_type"] as const;
export type EvalTask = (typeof TASKS)[number];

export type Interval = [number, number];

export type CoveragePoint = {
  /** Answer only when the model's confidence is at least this level. */
  min_confidence: Confidence;
  coverage: number | null;
  accuracy: number | null;
  n: number;
};

type BlockCounts = { n: number; n_missing: number; n_stale: number; abstention_rate: number | null };
type OverallCounts = { n_unsure: number; n_unlabelled: number };

/** T1, T2, T5. */
export type ClassificationBlock = BlockCounts & {
  accuracy: number | null;
  accuracy_ci95: Interval | null;
  accuracy_answered: number | null;
  macro_f1: number | null;
  macro_f1_ci95: Interval | null;
  weighted_f1: number | null;
  coverage_accuracy: CoveragePoint[];
};

/** T3, T4. */
export type SpanBlock = BlockCounts & {
  exact_match: number | null;
  exact_match_ci95: Interval | null;
  normalized_match: number | null;
  normalized_match_ci95: Interval | null;
};

export type ClassMetrics = { precision: number; recall: number; f1: number; support: number };

type RunBase = {
  model: string;
  prompt_version: string;
  kind: "model" | "baseline";
  split: string;
  task: EvalTask;
  schema_version: string;
  taxonomy_version: number | string;
};

export type ClassificationRun = RunBase & {
  family: "classification";
  by_source: Partial<Record<EvalSource, ClassificationBlock>>;
  overall: ClassificationBlock & OverallCounts;
  per_class: Record<string, ClassMetrics>;
  /** Rows = Labels, columns = model outputs; `abstain` last. */
  confusion_matrix: { labels: string[]; matrix: number[][] };
};

export type SpanRun = RunBase & {
  family: "span";
  by_source: Partial<Record<EvalSource, SpanBlock>>;
  overall: SpanBlock & OverallCounts;
};

export type EvalRun = ClassificationRun | SpanRun;

export type Kappa = { cohens_kappa: number | null; n: number };

/** The low-confidence threshold chosen on the dev curve (ticket 21); absent until then. */
export type Threshold = { model: string; prompt_version: string; task: EvalTask; min_confidence: Confidence };

export type EvalReport = {
  git_sha: string;
  created_at: string;
  /** `1` once the taxonomy is frozen, `"v1-draft"` until then. */
  taxonomy_version: number | string;
  synthetic: boolean;
  bootstrap: { resamples: number; seed: number; level: number };
  label_status: Record<string, { items: number; labelled: number }>;
  runs: EvalRun[];
  skipped: { model: string; prompt_version: string; split: string; task: string; reason: string }[];
  agreement: Kappa & { task: string; subset_size: number; by_task: Record<string, Kappa> };
  noise_audit: {
    agreement_with_official: number | null;
    n: number;
    n_unsure: number;
    n_unmapped: number;
    n_multi_label: number;
  };
  thresholds: Threshold[];
};

// --- guards ---------------------------------------------------------------------------

class ReportError extends Error {}

type Obj = Record<string, unknown>;

function fail(at: string, what: string): never {
  throw new ReportError(`latest.json: ${at} ${what}`);
}

function obj(v: unknown, at: string): Obj {
  if (typeof v !== "object" || v === null || Array.isArray(v)) fail(at, "must be an object");
  return v as Obj;
}

function arr(v: unknown, at: string): unknown[] {
  if (!Array.isArray(v)) fail(at, "must be an array");
  return v;
}

function str(v: unknown, at: string): string {
  if (typeof v !== "string") fail(at, "must be a string");
  return v;
}

function num(v: unknown, at: string): number {
  if (typeof v !== "number" || !Number.isFinite(v)) fail(at, "must be a number");
  return v;
}

function int(v: unknown, at: string): number {
  const n = num(v, at);
  if (!Number.isInteger(n) || n < 0) fail(at, "must be a count");
  return n;
}

function bool(v: unknown, at: string): boolean {
  if (typeof v !== "boolean") fail(at, "must be true or false");
  return v;
}

function oneOf<T extends string>(v: unknown, values: readonly T[], at: string): T {
  if (!values.includes(v as T)) fail(at, `must be one of ${values.join(", ")}`);
  return v as T;
}

function rate(v: unknown, at: string): number | null {
  if (v === null) return null;
  const n = num(v, at);
  if (n < -1 || n > 1) fail(at, "must be between -1 and 1");
  return n;
}

function interval(v: unknown, at: string): Interval | null {
  if (v === null) return null;
  const a = arr(v, at);
  if (a.length !== 2) fail(at, "must be [low, high]");
  return [num(a[0], `${at}[0]`), num(a[1], `${at}[1]`)];
}

function counts(o: Obj, at: string): BlockCounts {
  return {
    n: int(o.n, `${at}.n`),
    n_missing: int(o.n_missing, `${at}.n_missing`),
    n_stale: int(o.n_stale, `${at}.n_stale`),
    abstention_rate: rate(o.abstention_rate, `${at}.abstention_rate`),
  };
}

function classificationBlock(v: unknown, at: string): ClassificationBlock {
  const o = obj(v, at);
  return {
    ...counts(o, at),
    accuracy: rate(o.accuracy, `${at}.accuracy`),
    accuracy_ci95: interval(o.accuracy_ci95, `${at}.accuracy_ci95`),
    accuracy_answered: rate(o.accuracy_answered, `${at}.accuracy_answered`),
    macro_f1: rate(o.macro_f1, `${at}.macro_f1`),
    macro_f1_ci95: interval(o.macro_f1_ci95, `${at}.macro_f1_ci95`),
    weighted_f1: rate(o.weighted_f1, `${at}.weighted_f1`),
    coverage_accuracy: arr(o.coverage_accuracy, `${at}.coverage_accuracy`).map((p, i) => {
      const pt = obj(p, `${at}.coverage_accuracy[${i}]`);
      const pat = `${at}.coverage_accuracy[${i}]`;
      return {
        min_confidence: oneOf(pt.min_confidence, CONFIDENCES, `${pat}.min_confidence`),
        coverage: rate(pt.coverage, `${pat}.coverage`),
        accuracy: rate(pt.accuracy, `${pat}.accuracy`),
        n: int(pt.n, `${pat}.n`),
      };
    }),
  };
}

function spanBlock(v: unknown, at: string): SpanBlock {
  const o = obj(v, at);
  return {
    ...counts(o, at),
    exact_match: rate(o.exact_match, `${at}.exact_match`),
    exact_match_ci95: interval(o.exact_match_ci95, `${at}.exact_match_ci95`),
    normalized_match: rate(o.normalized_match, `${at}.normalized_match`),
    normalized_match_ci95: interval(o.normalized_match_ci95, `${at}.normalized_match_ci95`),
  };
}

function overallCounts(o: Obj, at: string): OverallCounts {
  return { n_unsure: int(o.n_unsure, `${at}.n_unsure`), n_unlabelled: int(o.n_unlabelled, `${at}.n_unlabelled`) };
}

function taxonomyVersion(v: unknown, at: string): number | string {
  if (typeof v === "string" && v !== "") return v;
  if (typeof v === "number" && Number.isInteger(v) && v > 0) return v;
  fail(at, 'must be a positive integer or a version string such as "v1-draft"');
}

function bySource<B>(v: unknown, at: string, block: (v: unknown, at: string) => B): Partial<Record<EvalSource, B>> {
  const o = obj(v, at);
  const out: Partial<Record<EvalSource, B>> = {};
  for (const key of Object.keys(o)) {
    out[oneOf(key, SOURCES, `${at} key`)] = block(o[key], `${at}.${key}`);
  }
  return out;
}

function confusionMatrix(v: unknown, at: string): ClassificationRun["confusion_matrix"] {
  const o = obj(v, at);
  const labels = arr(o.labels, `${at}.labels`).map((l, i) => str(l, `${at}.labels[${i}]`));
  const matrix = arr(o.matrix, `${at}.matrix`).map((row, i) =>
    arr(row, `${at}.matrix[${i}]`).map((c, j) => int(c, `${at}.matrix[${i}][${j}]`)),
  );
  if (matrix.length !== labels.length || matrix.some((row) => row.length !== labels.length)) {
    fail(at, `must be a ${labels.length}×${labels.length} matrix`);
  }
  return { labels, matrix };
}

function run(v: unknown, at: string): EvalRun {
  const o = obj(v, at);
  const base: RunBase = {
    model: str(o.model, `${at}.model`),
    prompt_version: str(o.prompt_version, `${at}.prompt_version`),
    kind: oneOf(o.kind, ["model", "baseline"] as const, `${at}.kind`),
    split: str(o.split, `${at}.split`),
    task: oneOf(o.task, TASKS, `${at}.task`),
    schema_version: str(o.schema_version, `${at}.schema_version`),
    taxonomy_version: taxonomyVersion(o.taxonomy_version, `${at}.taxonomy_version`),
  };
  const overall = obj(o.overall, `${at}.overall`);
  if ("exact_match" in overall) {
    return {
      ...base,
      family: "span",
      by_source: bySource(o.by_source, `${at}.by_source`, spanBlock),
      overall: { ...spanBlock(overall, `${at}.overall`), ...overallCounts(overall, `${at}.overall`) },
    };
  }
  const perClass = obj(o.per_class, `${at}.per_class`);
  return {
    ...base,
    family: "classification",
    by_source: bySource(o.by_source, `${at}.by_source`, classificationBlock),
    overall: { ...classificationBlock(overall, `${at}.overall`), ...overallCounts(overall, `${at}.overall`) },
    per_class: Object.fromEntries(
      Object.entries(perClass).map(([label, m]) => {
        const c = obj(m, `${at}.per_class.${label}`);
        const cat = `${at}.per_class.${label}`;
        return [
          label,
          {
            precision: num(c.precision, `${cat}.precision`),
            recall: num(c.recall, `${cat}.recall`),
            f1: num(c.f1, `${cat}.f1`),
            support: int(c.support, `${cat}.support`),
          },
        ];
      }),
    ),
    confusion_matrix: confusionMatrix(o.confusion_matrix, `${at}.confusion_matrix`),
  };
}

function kappa(v: unknown, at: string): Kappa {
  const o = obj(v, at);
  return { cohens_kappa: rate(o.cohens_kappa, `${at}.cohens_kappa`), n: int(o.n, `${at}.n`) };
}

export function parseEvalReport(data: unknown): EvalReport {
  const o = obj(data, "the file");
  const bootstrap = obj(o.bootstrap, "bootstrap");
  const labelStatus = obj(o.label_status, "label_status");
  const agreement = obj(o.agreement, "agreement");
  const audit = obj(o.noise_audit, "noise_audit");
  const byTask = obj(agreement.by_task, "agreement.by_task");
  return {
    git_sha: str(o.git_sha, "git_sha"),
    created_at: str(o.created_at, "created_at"),
    taxonomy_version: taxonomyVersion(o.taxonomy_version, "taxonomy_version"),
    synthetic: bool(o.synthetic, "synthetic"),
    bootstrap: {
      resamples: int(bootstrap.resamples, "bootstrap.resamples"),
      seed: int(bootstrap.seed, "bootstrap.seed"),
      level: num(bootstrap.level, "bootstrap.level"),
    },
    label_status: Object.fromEntries(
      Object.entries(labelStatus).map(([split, s]) => {
        const st = obj(s, `label_status.${split}`);
        return [
          split,
          { items: int(st.items, `label_status.${split}.items`), labelled: int(st.labelled, `label_status.${split}.labelled`) },
        ];
      }),
    ),
    runs: arr(o.runs, "runs").map((r, i) => run(r, `runs[${i}]`)),
    skipped: arr(o.skipped, "skipped").map((s, i) => {
      const sk = obj(s, `skipped[${i}]`);
      return {
        model: str(sk.model, `skipped[${i}].model`),
        prompt_version: str(sk.prompt_version, `skipped[${i}].prompt_version`),
        split: str(sk.split, `skipped[${i}].split`),
        task: str(sk.task, `skipped[${i}].task`),
        reason: str(sk.reason, `skipped[${i}].reason`),
      };
    }),
    agreement: {
      ...kappa(agreement, "agreement"),
      task: str(agreement.task, "agreement.task"),
      subset_size: int(agreement.subset_size, "agreement.subset_size"),
      by_task: Object.fromEntries(Object.entries(byTask).map(([t, k]) => [t, kappa(k, `agreement.by_task.${t}`)])),
    },
    noise_audit: {
      agreement_with_official: rate(audit.agreement_with_official, "noise_audit.agreement_with_official"),
      n: int(audit.n, "noise_audit.n"),
      n_unsure: int(audit.n_unsure, "noise_audit.n_unsure"),
      n_unmapped: int(audit.n_unmapped, "noise_audit.n_unmapped"),
      n_multi_label: int(audit.n_multi_label, "noise_audit.n_multi_label"),
    },
    thresholds:
      o.thresholds === undefined
        ? []
        : arr(o.thresholds, "thresholds").map((t, i) => {
            const th = obj(t, `thresholds[${i}]`);
            return {
              model: str(th.model, `thresholds[${i}].model`),
              prompt_version: str(th.prompt_version, `thresholds[${i}].prompt_version`),
              task: oneOf(th.task, TASKS, `thresholds[${i}].task`),
              min_confidence: oneOf(th.min_confidence, CONFIDENCES, `thresholds[${i}].min_confidence`),
            };
          }),
  };
}

// The file paths are parameters (tests, the example page), so Turbopack cannot scope them;
// the pages that read them are fully static, so nothing needs tracing for runtime.
export function loadEvalReport(file: string = EVAL_RESULTS_FILE): EvalReport {
  return parseEvalReport(JSON.parse(readFileSync(/*turbopackIgnore: true*/ file, "utf8")));
}

function versionNumber(version: string): number {
  const match = /^v?(\d+)$/.exec(version.trim());
  return match ? Number(match[1]) : -1;
}

/**
 * The annotation guideline versions each annotator (A: domain expert, B: second
 * annotator) has used in `eval/labels.csv`, oldest first (v2 < v10, as the harness).
 */
export function readGuidelineVersions(file: string = EVAL_LABELS_FILE): { A: string[]; B: string[] } {
  const [header, ...rows] = parseCsv(readFileSync(/*turbopackIgnore: true*/ file, "utf8"));
  const annotator = header.indexOf("annotator");
  const version = header.indexOf("guideline_version");
  if (annotator === -1 || version === -1) throw new Error(`${file}: missing annotator or guideline_version`);
  const used = (who: string) =>
    [...new Set(rows.filter((r) => r[annotator] === who).map((r) => r[version]))].sort(
      (a, b) => versionNumber(a) - versionNumber(b) || a.localeCompare(b),
    );
  return { A: used("A"), B: used("B") };
}
