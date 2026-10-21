/**
 * What an AI badge says about its value (spec §9): who classified it, when, with which
 * prompt version, and the test-set accuracy of exactly that model and prompt version from
 * `eval/results/latest.json` (ticket 25). No number is ever made up: without a test run
 * with Labels for that task, model and prompt version, the badge says so.
 */
import { EVAL_RESULTS_FILE, loadEvalReport, type EvalReport } from "./evaluation";

export type BadgeRun = { task: string; model: string; promptVersion: string };

/**
 * Test-split accuracy of a model run: accuracy for the classification tasks (T1, T2),
 * exact match for the span tasks (T3, T4); null when there is no such run or it had no
 * Labels. T6 summaries are not scored on the test set (spec §7.2), so they never have one.
 */
export function testAccuracy(report: EvalReport | null, run: BadgeRun): number | null {
  const found = report?.runs.find(
    (r) =>
      r.split === "test" &&
      r.kind === "model" &&
      r.task === run.task &&
      r.model === run.model &&
      r.prompt_version === run.promptVersion,
  );
  if (!found) return null;
  return found.family === "classification" ? found.overall.accuracy : found.overall.exact_match;
}

let cached: { report: EvalReport | null } | undefined;

/**
 * latest.json as deployed, read once per server process. A file that cannot be read
 * gives no numbers (badges say "not yet evaluated") rather than a broken page; the
 * `/en/evaluation` build fails loudly on the same file.
 */
export function deployedEvalReport(): EvalReport | null {
  if (!cached) {
    try {
      cached = { report: loadEvalReport(EVAL_RESULTS_FILE) };
    } catch (e) {
      console.error("AI badges: cannot read eval/results/latest.json", e);
      cached = { report: null };
    }
  }
  return cached.report;
}

/** "v2" → "2", for "prompt v{n}". */
export function promptNumber(promptVersion: string): string {
  return promptVersion.replace(/^v/i, "");
}
