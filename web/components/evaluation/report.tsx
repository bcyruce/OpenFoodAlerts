import Link from "next/link";
import type { ReactNode } from "react";
import type { ClassificationRun, EvalReport, EvalRun, SpanRun } from "@/lib/evaluation";
import {
  comparisonRows,
  confusionTable,
  coverageSeries,
  formatInterval,
  formatPercent,
  formatRate,
  formatWithInterval,
  metricRows,
  NOT_DEFINED,
  SOURCE_LABELS,
  splitSections,
  TASK_LABELS,
  type SplitSection,
} from "@/lib/evaluation-view";
import { repoFileUrl } from "@/lib/repo";
import { REPO_URL } from "@/lib/site";
import { CoverageChart } from "./coverage-chart";

// The content of /en/evaluation (ticket 25, spec §7 and §9), rendered on the server from a
// parsed latest.json. English only. Every chart has its data table; tables have captions
// and header scopes; wide tables scroll in a focusable region.

export type EvaluationContext = {
  report: EvalReport;
  /** Guideline versions per annotator from eval/labels.csv; null for the synthetic example. */
  guidelines: { A: string[]; B: string[] } | null;
  /** docs/annotation_guidelines.md exists in this checkout. */
  guidelinesWritten: boolean;
};

const GUIDELINES_FILE = "docs/annotation_guidelines.md";

const CONFIDENCE_LEVELS: Record<string, string> = {
  high: "High confidence only",
  medium: "High + medium",
  low: "All answers",
};

const TABLE =
  "w-full border-collapse text-sm tabular-nums [&_td]:border [&_td]:border-slate-300 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-slate-300 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:align-bottom [&_th]:font-semibold [&_caption]:mb-1 [&_caption]:text-left [&_caption]:font-medium [&_caption]:text-slate-800";

function ScrollTable({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="mt-3 max-w-full overflow-x-auto" tabIndex={0} role="region" aria-label={label} data-testid={testId}>
      <table className={TABLE}>{children}</table>
    </div>
  );
}

function Disclosure({ summary, children, testId }: { summary: string; children: ReactNode; testId?: string }) {
  return (
    <details className="mt-3" data-testid={testId}>
      <summary className="cursor-pointer text-sm font-medium text-blue-800">{summary}</summary>
      {children}
    </details>
  );
}

function SyntheticBanner() {
  return (
    <div
      className="mt-6 border-4 border-red-800 bg-red-50 p-4 text-red-950"
      role="note"
      aria-label="Synthetic example"
      data-testid="synthetic-banner"
    >
      <p className="text-xl font-bold uppercase tracking-wide">Synthetic example — not real results</p>
      <p className="mt-2">
        Every number on this page comes from <code>eval/results/example.json</code>: invented Labels and an
        invented <code>synthetic-model</code>. It exists only to build and test this page before real Labels
        exist. Real results are on <Link href="/en/evaluation">/en/evaluation</Link>.
      </p>
    </div>
  );
}

function SyntheticTag({ synthetic }: { synthetic: boolean }) {
  return synthetic ? (
    <span className="ml-2 rounded bg-red-800 px-2 py-0.5 align-middle text-xs font-bold uppercase text-white">
      synthetic
    </span>
  ) : null;
}

function runName(run: Pick<EvalRun, "model" | "prompt_version" | "kind">): string {
  return `${run.model} (${run.kind === "baseline" ? "baseline" : "prompt"} ${run.prompt_version})`;
}

function taxonomyText(version: number | string): string {
  return typeof version === "number" ? `Taxonomy v${version} (frozen)` : `Taxonomy ${version} (draft, not frozen)`;
}

function GuidelinesLink({ written }: { written: boolean }) {
  return (
    <>
      <a href={repoFileUrl(GUIDELINES_FILE)}>annotation guidelines</a>
      {written ? null : " (coming: being written alongside the first Labels)"}
    </>
  );
}

// --- status -------------------------------------------------------------------------

function LabelStatus({ report, guidelines, guidelinesWritten }: EvaluationContext) {
  const splits = Object.entries(report.label_status).sort(([a], [b]) => (a === "test" ? -1 : b === "test" ? 1 : 0));
  const versions = (list: string[]) => (list.length ? list.join(", ") : "none yet");
  return (
    <section aria-labelledby="status" className="mt-10">
      <h2 id="status">Label status</h2>
      <ScrollTable label="Label status per split" testId="label-status">
        <caption>Items in the evaluation set and how many have a Label from the domain expert (annotator A)</caption>
        <thead>
          <tr>
            <th scope="col">Split</th>
            <th scope="col">Items</th>
            <th scope="col">Labelled</th>
          </tr>
        </thead>
        <tbody>
          {splits.map(([split, s]) => (
            <tr key={split}>
              <th scope="row">{split === "test" ? "test (frozen)" : split}</th>
              <td>{s.items}</td>
              <td>{s.labelled}</td>
            </tr>
          ))}
        </tbody>
      </ScrollTable>
      <ul>
        <li data-testid="guideline-versions">
          Guideline version used:{" "}
          {guidelines === null
            ? "none (the example's Labels are invented)"
            : `annotator A: ${versions(guidelines.A)}; annotator B: ${versions(guidelines.B)}`}
          . See the <GuidelinesLink written={guidelinesWritten} />.
        </li>
        <li>
          {taxonomyText(report.taxonomy_version)}; the T1 labels are listed on the <Link href="/en/data">data page</Link>.
        </li>
        <li>
          Results of commit{" "}
          {/^[0-9a-f]{40}$/.test(report.git_sha) ? (
            <a href={`${REPO_URL}/commit/${report.git_sha}`}>
              <code>{report.git_sha.slice(0, 7)}</code>
            </a>
          ) : (
            <code>{report.git_sha}</code>
          )}
          , computed {report.created_at.slice(0, 10)}. 95% intervals: percentile bootstrap over items,{" "}
          {report.bootstrap.resamples.toLocaleString("en-GB")} resamples, seed {report.bootstrap.seed}.
        </li>
      </ul>
    </section>
  );
}

function EmptyState({ report, guidelinesWritten }: EvaluationContext) {
  return (
    <section
      aria-labelledby="no-results"
      className="mt-8 border-l-4 border-blue-800 bg-blue-50 p-4"
      data-testid="evaluation-empty"
    >
      <h2 id="no-results" className="mt-0!">
        No results yet: labelling is in progress
      </h2>
      <p>
        The 300-item evaluation set is sampled and its inputs are frozen, but the domain expert has not labelled
        it yet. A metric needs Labels to compare with, so until then there are no numbers to show, not even for
        the baselines. This page is generated from <code>eval/results/latest.json</code> at every deployment and
        fills in by itself once Labels are committed; no number on this site is published before that.
      </p>
      {report.skipped.length > 0 ? (
        <p>
          Waiting for Labels:{" "}
          {report.skipped.map((s, i) => (
            <span key={`${s.model}-${s.split}-${s.task}`}>
              {i > 0 ? "; " : ""}
              {s.model} ({s.prompt_version}) on {s.split}, {TASK_LABELS[s.task as keyof typeof TASK_LABELS] ?? s.task}
            </span>
          ))}
          .
        </p>
      ) : null}
      <p>
        In the meantime: how the set was drawn and how it will be scored is under <a href="#method">Method</a>; the
        set itself, the <GuidelinesLink written={guidelinesWritten} /> and the command that recomputes everything
        are under <a href="#reproduce">Reproduce</a>.
      </p>
    </section>
  );
}

// --- comparison ---------------------------------------------------------------------

function Comparison({ report, section }: { report: EvalReport; section: SplitSection }) {
  const rows = comparisonRows(report, section.split);
  if (rows.length === 0) return null;
  const id = `comparison-${section.split}`;
  return (
    <section aria-labelledby={id} className="mt-8">
      <h3 id={id}>
        Model comparison, T1 Hazard category, {section.split} split
        <SyntheticTag synthetic={report.synthetic} />
      </h3>
      <ScrollTable label={`Model comparison on the ${section.split} split`} testId={`comparison-${section.split}`}>
        <caption>
          T1 on the {section.split} split, all sources together and macro-F1 per source; 95% intervals in brackets
        </caption>
        <thead>
          <tr>
            <th scope="col">Model or baseline</th>
            <th scope="col">Type</th>
            <th scope="col">n</th>
            <th scope="col">Accuracy</th>
            <th scope="col">Macro-F1</th>
            <th scope="col">Weighted-F1</th>
            <th scope="col">Abstained</th>
            {(["rasff", "nvwa", "openfda"] as const).map((s) => (
              <th scope="col" key={s}>
                Macro-F1 {SOURCE_LABELS[s]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.model}-${r.prompt_version}`}>
              <th scope="row">
                {r.model} <span className="font-normal">({r.prompt_version})</span>
              </th>
              <td>{r.kind}</td>
              <td>{r.overall.n}</td>
              <td>{formatWithInterval(r.overall.accuracy, r.overall.accuracy_ci95)}</td>
              <td>{formatWithInterval(r.overall.macro_f1, r.overall.macro_f1_ci95)}</td>
              <td>{formatRate(r.overall.weighted_f1)}</td>
              <td>{formatPercent(r.overall.abstention_rate)}</td>
              {(["rasff", "nvwa", "openfda"] as const).map((s) => (
                <td key={s}>
                  {r.bySource[s]
                    ? `${formatWithInterval(r.bySource[s].macro_f1, r.bySource[s].macro_f1_ci95)}, n=${r.bySource[s].n}`
                    : NOT_DEFINED}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </ScrollTable>
      <p className="text-sm">
        Overlapping intervals mean the difference is not established on this sample. If the language model does
        not clearly beat the baselines, that is what this table says; nothing is left out (spec §7.2).
      </p>
    </section>
  );
}

// --- one run ------------------------------------------------------------------------

function ClassificationMetrics({ run, caption }: { run: ClassificationRun; caption: string }) {
  return (
    <ScrollTable label={caption}>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Scope</th>
          <th scope="col">n</th>
          <th scope="col">Accuracy (95% CI)</th>
          <th scope="col">Accuracy of answers</th>
          <th scope="col">Macro-F1 (95% CI)</th>
          <th scope="col">Weighted-F1</th>
          <th scope="col">Abstained</th>
          <th scope="col">No cached output / stale</th>
        </tr>
      </thead>
      <tbody>
        {metricRows(run).map(({ scope, label, block }) => (
          <tr key={scope}>
            <th scope="row">{label}</th>
            <td>{block.n}</td>
            <td>{formatWithInterval(block.accuracy, block.accuracy_ci95)}</td>
            <td>{formatRate(block.accuracy_answered)}</td>
            <td>{formatWithInterval(block.macro_f1, block.macro_f1_ci95)}</td>
            <td>{formatRate(block.weighted_f1)}</td>
            <td>{formatPercent(block.abstention_rate)}</td>
            <td>
              {block.n_missing} / {block.n_stale}
            </td>
          </tr>
        ))}
      </tbody>
    </ScrollTable>
  );
}

function SpanMetrics({ run, caption }: { run: SpanRun; caption: string }) {
  return (
    <ScrollTable label={caption}>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Scope</th>
          <th scope="col">n</th>
          <th scope="col">Exact match</th>
          <th scope="col">95% CI</th>
          <th scope="col">Normalised match</th>
          <th scope="col">95% CI</th>
          <th scope="col">Abstained</th>
          <th scope="col">No cached output / stale</th>
        </tr>
      </thead>
      <tbody>
        {metricRows(run).map(({ scope, label, block }) => {
          const b = block as SpanRun["overall"];
          return (
            <tr key={scope}>
              <th scope="row">{label}</th>
              <td>{b.n}</td>
              <td>{formatRate(b.exact_match)}</td>
              <td>{formatInterval(b.exact_match_ci95)}</td>
              <td>{formatRate(b.normalized_match)}</td>
              <td>{formatInterval(b.normalized_match_ci95)}</td>
              <td>{formatPercent(b.abstention_rate)}</td>
              <td>
                {b.n_missing} / {b.n_stale}
              </td>
            </tr>
          );
        })}
      </tbody>
    </ScrollTable>
  );
}

function Coverage({ run, report, testId }: { run: ClassificationRun; report: EvalReport; testId: string }) {
  const chart = coverageSeries(run, report.thresholds);
  const title = `Coverage and accuracy by confidence level, ${runName(run)}, ${TASK_LABELS[run.task]}, ${run.split}`;
  return (
    <figure className="mt-4" data-testid={testId}>
      <figcaption className="text-sm font-medium text-slate-800">
        Coverage–accuracy curve
        {chart.threshold
          ? `: the chosen low-confidence threshold (confidence ≥ ${chart.threshold.min_confidence}) is marked`
          : ": no low-confidence threshold chosen yet (ticket 21 picks it on the dev curve)"}
      </figcaption>
      <CoverageChart
        chart={chart}
        label={`${title}. The numbers are in the data table below.`}
        testId={`${testId}-chart`}
      />
      <Disclosure summary="Data table" testId={`${testId}-table`}>
        <ScrollTable label={`Data table: ${title}`}>
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">Answer when</th>
              {chart.series.map((s) => (
                <th scope="col" key={s.scope}>
                  {s.label}: coverage, accuracy (n answered)
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chart.series[0].points.map((p, i) => (
              <tr key={p.min_confidence}>
                <th scope="row">
                  {CONFIDENCE_LEVELS[p.min_confidence]}
                  {chart.threshold?.min_confidence === p.min_confidence ? " (chosen threshold)" : ""}
                </th>
                {chart.series.map((s) => {
                  const q = s.points[i];
                  return (
                    <td key={s.scope}>
                      {q ? `${formatPercent(q.coverage)}, ${formatPercent(q.accuracy)} (${q.n})` : NOT_DEFINED}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </ScrollTable>
      </Disclosure>
    </figure>
  );
}

function PerClass({ run }: { run: ClassificationRun }) {
  const rows = Object.entries(run.per_class).sort(([, a], [, b]) => b.support - a.support);
  return (
    <Disclosure summary="Precision, recall and F1 per label">
      <ScrollTable label={`Per-label metrics, ${runName(run)}, ${run.split}`}>
        <caption className="sr-only">
          Precision, recall, F1 and support per label, {runName(run)}, {TASK_LABELS[run.task]}, {run.split}
        </caption>
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">Precision</th>
            <th scope="col">Recall</th>
            <th scope="col">F1</th>
            <th scope="col">Support (Labels)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, m]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{formatRate(m.precision)}</td>
              <td>{formatRate(m.recall)}</td>
              <td>{formatRate(m.f1)}</td>
              <td>{m.support}</td>
            </tr>
          ))}
        </tbody>
      </ScrollTable>
    </Disclosure>
  );
}

function Confusion({ run, testId }: { run: ClassificationRun; testId: string }) {
  const table = confusionTable(run);
  const title = `Confusion matrix, ${runName(run)}, ${TASK_LABELS[run.task]}, ${run.split}`;
  return (
    <Disclosure summary="Confusion matrix" testId={testId}>
      <p className="text-sm">
        Rows: the Label; columns: the model output (<code>abstain</code> last). Diagonal cells are correct.
        {table.hidden.length > 0
          ? ` Labels that occur in neither are left out: ${table.hidden.join(", ")}.`
          : ""}
      </p>
      <ScrollTable label={title}>
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            <th scope="col">Label \ output</th>
            {table.columns.map((c) => (
              <th scope="col" key={c} className="min-w-16">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r, i) => (
            <tr key={r}>
              <th scope="row">{r}</th>
              {table.cells[i].map((n, j) => (
                <td
                  key={table.columns[j]}
                  className={table.columns[j] === r ? "bg-blue-100 font-semibold" : n === 0 ? "text-slate-500" : ""}
                >
                  {n}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </ScrollTable>
    </Disclosure>
  );
}

function RunResult({ run, report }: { run: EvalRun; report: EvalReport }) {
  const id = `run-${run.split}-${run.task}-${run.model}-${run.prompt_version}`.replace(/[^a-zA-Z0-9_-]/g, "-");
  const caption = `${TASK_LABELS[run.task]}, ${runName(run)}, ${run.split} split, per source and overall`;
  return (
    <section aria-labelledby={id} className="mt-6" data-testid={id}>
      <h4 id={id} className="text-base font-semibold text-slate-900">
        {runName(run)}
        {run.kind === "baseline" ? <span className="font-normal"> — baseline</span> : null}
      </h4>
      {run.family === "classification" ? (
        <>
          <ClassificationMetrics run={run} caption={caption} />
          <Coverage run={run} report={report} testId={`${id}-coverage`} />
          <PerClass run={run} />
          <Confusion run={run} testId={`${id}-confusion`} />
        </>
      ) : (
        <SpanMetrics run={run} caption={caption} />
      )}
    </section>
  );
}

function SplitResults({ report, section }: { report: EvalReport; section: SplitSection }) {
  const id = `split-${section.split}`;
  return (
    <section aria-labelledby={id} className="mt-12" data-testid={id}>
      <h2 id={id}>
        {section.split === "test" ? "Test split (frozen)" : section.split === "dev" ? "Dev split" : `${section.split} split`}
        <SyntheticTag synthetic={report.synthetic} />
      </h2>
      <p>
        {section.labelled} of {section.items} items labelled.{" "}
        {section.split === "test"
          ? "The test split is frozen and only scored for release tags; it is the estimate to quote."
          : section.split === "dev"
            ? "The dev split is used to develop prompts and to choose the low-confidence threshold, so its numbers are optimistic. Quote the test split."
            : null}
      </p>
      <Comparison report={report} section={section} />
      {section.tasks.map(({ task, runs }) => (
        <section key={task} aria-labelledby={`${id}-${task}`} className="mt-10">
          <h3 id={`${id}-${task}`}>{TASK_LABELS[task]}</h3>
          {runs.map((run) => (
            <RunResult key={`${run.model}-${run.prompt_version}`} run={run} report={report} />
          ))}
        </section>
      ))}
    </section>
  );
}

// --- agreement, noise audit -----------------------------------------------------------

function Agreement({ report }: { report: EvalReport }) {
  const a = report.agreement;
  const measured = a.n > 0;
  return (
    <section aria-labelledby="agreement" className="mt-12" data-testid="agreement">
      <h2 id="agreement">
        Agreement between annotators (Cohen’s κ)
        <SyntheticTag synthetic={report.synthetic} />
      </h2>
      <p>
        A second annotator with a food-safety background labels a {a.subset_size}-item subset independently. If κ
        on T1 is below 0.6, the guidelines are revised before metrics are published (spec §7.1).{" "}
        {measured
          ? `T1: κ = ${formatRate(a.cohens_kappa)} on ${a.n} items (pairs where either annotator was unsure are left out).`
          : "Not measured yet: no second annotator has labelled the subset, so every Label comes from one annotator."}
      </p>
      <ScrollTable label="Cohen’s kappa per task">
        <caption>Cohen’s κ between annotators A and B per task (— = not defined)</caption>
        <thead>
          <tr>
            <th scope="col">Task</th>
            <th scope="col">κ</th>
            <th scope="col">Items compared</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(a.by_task).map(([task, k]) => (
            <tr key={task}>
              <th scope="row">{TASK_LABELS[task as keyof typeof TASK_LABELS] ?? task}</th>
              <td>{formatRate(k.cohens_kappa)}</td>
              <td>{k.n}</td>
            </tr>
          ))}
        </tbody>
      </ScrollTable>
    </section>
  );
}

function NoiseAudit({ report }: { report: EvalReport }) {
  const audit = report.noise_audit;
  return (
    <section aria-labelledby="noise-audit" className="mt-12" data-testid="noise-audit">
      <h2 id="noise-audit">
        Noise audit of the official RASFF categories
        <SyntheticTag synthetic={report.synthetic} />
      </h2>
      <p>
        On the 60 RASFF items the domain expert’s T1 Label is compared with the official RASFF Hazard categories
        mapped through the taxonomy. This measures how often the official classification itself disagrees with a
        careful reading, which bounds what any model can score against official labels. An item agrees when the
        Label is one of the labels of its official categories.
      </p>
      <ScrollTable label="Noise audit">
        <caption>Domain expert’s Label against the official RASFF category</caption>
        <tbody>
          <tr>
            <th scope="row">Agreement with the official category</th>
            <td data-testid="noise-audit-agreement">{formatPercent(audit.agreement_with_official)}</td>
          </tr>
          <tr>
            <th scope="row">Items compared</th>
            <td>{audit.n}</td>
          </tr>
          <tr>
            <th scope="row">Official categories mapping to more than one label</th>
            <td>{audit.n_multi_label}</td>
          </tr>
          <tr>
            <th scope="row">No mappable official category</th>
            <td>{audit.n_unmapped}</td>
          </tr>
          <tr>
            <th scope="row">Annotator unsure (left out)</th>
            <td>{audit.n_unsure}</td>
          </tr>
        </tbody>
      </ScrollTable>
    </section>
  );
}

// --- fixed text -------------------------------------------------------------------------

function Method() {
  return (
    <section aria-labelledby="method" className="mt-12">
      <h2 id="method">Method</h2>
      <p>
        Full details: <a href={repoFileUrl("eval/README.md")}>eval/README.md</a> and spec §7.
      </p>
      <h3>Evaluation set</h3>
      <ul>
        <li>
          300 Notifications: NVWA 120 (food, since 4 October 2023), openFDA 120, RASFF 60; stratified by Source ×
          hazard group with a fixed seed and at least 8 items per T1 label where the sampling frame allows. Split
          into dev 100 and test 200; the test split is frozen.
        </li>
        <li>
          T1 is scored on all three Sources (on RASFF from the one-line subject only); T2–T5 on NVWA and openFDA.
          Every number is reported per Source and for all Sources together.
        </li>
        <li>Labels are by the domain expert (annotator A); a second annotator labels a 60-item subset for κ.</li>
      </ul>
      <h3>Metrics</h3>
      <ul>
        <li>
          <strong>Abstention counts as wrong.</strong> Accuracy is over all labelled items, abstentions included;
          “accuracy of answers” leaves them out; “abstained” is their share. An item without a cached model output,
          or with one made for an older input, also counts as an abstention.
        </li>
        <li>
          Macro-F1 averages F1 over the labels present in the Labels or the outputs (each label counts the same);
          weighted-F1 weights by the number of Labels.
        </li>
        <li>
          T3 (Hazard text) and T4 (country): exact match, and a normalised match (T3: case, Unicode punctuation and
          spacing ignored; T4: both sides mapped to ISO 3166 codes).
        </li>
        <li>
          Coverage–accuracy curve: the model answers only when its confidence is at least high / medium / low.
          Coverage is the share answered, accuracy the share of those answers that is right. The “low confidence”
          threshold for the website is chosen on the dev curve and marked here once chosen.
        </li>
        <li>95% intervals: percentile bootstrap over items (1,000 resamples).</li>
      </ul>
    </section>
  );
}

function Baselines() {
  return (
    <section aria-labelledby="baselines" className="mt-12">
      <h2 id="baselines">Baselines</h2>
      <p>Both run on T1 only, from the same committed files, and appear in the comparison tables above.</p>
      <ul>
        <li>
          <strong>baseline-keywords (kw1)</strong>: transparent English and Dutch keyword rules mapped to T1
          labels; no match means abstain. Caveat: the NVWA and openFDA items were stratified by the output of these
          same rules, which favours this baseline.
        </li>
        <li>
          <strong>baseline-tfidf-lr (silver1)</strong>: TF-IDF over character 2–5-grams with logistic regression,
          trained on the RASFF silver set (subject → official category). It never abstains. Caveat: it learns from
          one-line, mostly English RASFF subjects and is tested on Dutch NVWA pages and long English openFDA recall
          texts (domain and language shift), and the silver set is still small until the RASFF backfill.
        </li>
      </ul>
    </section>
  );
}

function Limitations({ taxonomyVersion }: { taxonomyVersion: number | string }) {
  return (
    <section aria-labelledby="limitations" className="mt-12" data-testid="limitations">
      <h2 id="limitations">Limitations</h2>
      <ul>
        <li>
          <strong>One annotator</strong> until the second annotator’s κ is available: the Labels encode one
          expert’s reading of the guidelines.
        </li>
        <li>
          <strong>Stratified, not representative.</strong> The label floors over-sample rare hazards on purpose, so
          the metrics describe this sample, not the mix of Notifications on the site. Reweighting to the sampling
          frame is not applied (the counts needed for it are in <code>eval/sampling.json</code>). Some rare T1
          labels have fewer than 8 items (<code>shortfall</code> in the same file), so their per-label numbers rest
          on a handful of cases.
        </li>
        <li>
          <strong>Keyword baseline stratification.</strong> NVWA and openFDA strata come from the keyword rules
          that are also a baseline, which flatters that baseline.
        </li>
        <li>
          <strong>Domain shift of the silver-trained baseline</strong>: trained on RASFF subjects, tested on NVWA
          and openFDA texts in other languages and lengths.
        </li>
        <li>
          <strong>NVWA product-type rule.</strong> NVWA items come from Notifications the Product type rule calls
          food; the rule leaves out unclear (“pending”) cases, so T5 on NVWA sees almost only food and some real
          food warnings never enter the set.
        </li>
        <li>
          <strong>RASFF hazards.</strong> In a sample of recent RASFF public details, 24% named no Hazard (24 of
          100). The RASFF items and the silver set can only use Notifications that do, and RASFF models see the
          subject line only.
        </li>
        <li>
          {typeof taxonomyVersion === "number"
            ? `Taxonomy v${taxonomyVersion} is frozen; a new version means relabelling the set.`
            : "The taxonomy is still a draft; freezing it can change labels and strata, and some Labels may have to be redone."}{" "}
          Self-reported confidence is poorly calibrated, which is why the threshold comes from the curve, not from
          the model’s own word.
        </li>
      </ul>
    </section>
  );
}

function References() {
  return (
    <section aria-labelledby="references" className="mt-12" data-testid="references">
      <h2 id="references">Related work (cited, not ranked)</h2>
      <p>
        Earlier work on classifying food-safety notifications. Their data, label sets and splits differ from ours,
        so their numbers are not comparable with the ones on this page and are not shown next to them.
      </p>
      <ul>
        <li>
          Nogales et al. (2022). <em>Food Control</em> 134, article 108697.
        </li>
        <li>
          Sari et al. (2025). <em>British Food Journal</em>.{" "}
          <a href="https://doi.org/10.1108/BFJ-10-2024-1072">doi:10.1108/BFJ-10-2024-1072</a>
        </li>
        <li>
          German Federal Institute for Risk Assessment (BfR). RASNEX. Zenodo.{" "}
          <a href="https://doi.org/10.5281/zenodo.4322555">doi:10.5281/zenodo.4322555</a>
        </li>
      </ul>
    </section>
  );
}

function Reproduce({ guidelinesWritten, synthetic }: { guidelinesWritten: boolean; synthetic: boolean }) {
  return (
    <section aria-labelledby="reproduce" className="mt-12" data-testid="reproduce">
      <h2 id="reproduce">Reproduce</h2>
      <ul>
        <li>
          Evaluation set (CC BY 4.0): <a href={repoFileUrl("eval/items.csv")}>eval/items.csv</a> (items and the frozen
          model input) and <a href={repoFileUrl("eval/labels.csv")}>eval/labels.csv</a> (Labels).
        </li>
        <li>
          The <GuidelinesLink written={guidelinesWritten} /> (<code>{GUIDELINES_FILE}</code>, versioned).
        </li>
        <li>
          Cached model outputs: <a href={`${REPO_URL}/tree/main/eval/cache`}>eval/cache/</a>; scoring code:{" "}
          <a href={`${REPO_URL}/tree/main/pipeline/src/openfoodalerts/eval`}>pipeline/src/openfoodalerts/eval/</a>.
        </li>
        <li>
          The numbers on this page:{" "}
          {synthetic ? (
            <a href={repoFileUrl("eval/results/example.json")}>eval/results/example.json</a>
          ) : (
            <a href={repoFileUrl("eval/results/latest.json")}>eval/results/latest.json</a>
          )}
          .
        </li>
      </ul>
      <p>
        One command recomputes them from the committed files, offline, without an API key (needs{" "}
        <a href="https://docs.astral.sh/uv/">uv</a> and make):
      </p>
      <pre className="mt-3 overflow-x-auto rounded bg-slate-100 p-3 text-sm" data-testid="reproduce-command">
        <code>{`git clone ${REPO_URL}.git
cd ${REPO_URL.split("/").pop()}
make eval              # dev split
make eval SPLIT=test   # the frozen test split`}</code>
      </pre>
    </section>
  );
}

export function EvaluationReport(context: EvaluationContext) {
  const { report } = context;
  const sections = splitSections(report);
  return (
    <>
      {report.synthetic ? <SyntheticBanner /> : null}
      <LabelStatus {...context} />
      {sections.length === 0 ? <EmptyState {...context} /> : null}
      {sections.map((section) => (
        <SplitResults key={section.split} report={report} section={section} />
      ))}
      <Agreement report={report} />
      <NoiseAudit report={report} />
      <Baselines />
      <Method />
      <Limitations taxonomyVersion={report.taxonomy_version} />
      <References />
      <Reproduce guidelinesWritten={context.guidelinesWritten} synthetic={report.synthetic} />
    </>
  );
}
