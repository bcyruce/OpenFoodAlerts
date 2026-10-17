import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EvaluationPage } from "@/components/evaluation/page";
import { EVAL_RESULTS_FILE } from "@/lib/evaluation";

// Static and English only (spec §9); /nl/evaluation and /zh/evaluation redirect here
// (next.config.ts). Generated from eval/results/latest.json at build time, i.e. at every
// deployment. The synthetic example renders at ./example in test builds only.
export const ensureStatic = "navigation";

const TITLE = "Evaluation";

export async function generateMetadata({ params }: PageProps<"/[locale]/evaluation">): Promise<Metadata> {
  if ((await params).locale !== "en") return {};
  return {
    title: TITLE,
    description:
      "How well the AI classifications of OpenFoodAlerts do on a hand-labelled evaluation set: metrics per source with confidence intervals, confusion matrices, coverage–accuracy curves, baselines, annotator agreement and limitations.",
    alternates: { canonical: "/en/evaluation", languages: { en: "/en/evaluation" } },
  };
}

export default async function Page({ params }: PageProps<"/[locale]/evaluation">) {
  if ((await params).locale !== "en") notFound();
  return <EvaluationPage file={EVAL_RESULTS_FILE} title={TITLE} />;
}
