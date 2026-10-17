import { existsSync } from "node:fs";
import path from "node:path";
import { Prose } from "@/components/prose";
import { loadEvalReport, readGuidelineVersions } from "@/lib/evaluation";
import { REPO_ROOT } from "@/lib/repo";
import { EvaluationReport } from "./report";

/**
 * /en/evaluation for one results file, read at build time (sync fs, so the page stays
 * static). An invalid file fails the build with the name of the broken field.
 */
export function EvaluationPage({ file, title }: { file: string; title: string }) {
  const report = loadEvalReport(file);
  return (
    <article data-synthetic={report.synthetic ? "true" : "false"}>
      <h1 className="text-3xl font-semibold text-slate-900">{title}</h1>
      <p className="mt-2 max-w-prose text-slate-700">
        OpenFoodAlerts uses a language model to fill in fields that the Sources leave empty: the hazard category,
        product category, hazard, country of origin and product type (tasks T1–T5). This page reports how well it
        does on a hand-labelled evaluation set, next to two simple baselines, per Source and for all Sources
        together. It is generated from the committed results file at every deployment; one command reproduces
        every number (see <a href="#reproduce">Reproduce</a>). Where the website shows an AI classification, the
        official record remains the reference.
      </p>
      <Prose wide>
        <EvaluationReport
          report={report}
          guidelines={report.synthetic ? null : readGuidelineVersions()}
          guidelinesWritten={existsSync(path.join(REPO_ROOT, "docs", "annotation_guidelines.md"))}
        />
      </Prose>
    </article>
  );
}
