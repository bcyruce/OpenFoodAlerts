import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EvaluationPage } from "@/components/evaluation/page";
import { EVAL_EXAMPLE_FILE } from "@/lib/evaluation";

// The page rendered from the SYNTHETIC eval/results/example.json, so the smoke tests can
// check the full layout before real Labels exist. Test builds only: without
// OFA_EVAL_EXAMPLE=1 at build time (set by `make smoke`, never by a deployment) this is a
// 404. Never indexed, never in the sitemap, and marked synthetic all over.
export const ensureStatic = "navigation";

const ENABLED = process.env.OFA_EVAL_EXAMPLE === "1";
const TITLE = "Evaluation: synthetic example";

export async function generateMetadata({ params }: PageProps<"/[locale]/evaluation/example">): Promise<Metadata> {
  if (!ENABLED || (await params).locale !== "en") return {};
  return { title: TITLE, robots: { index: false, follow: false } };
}

export default async function Page({ params }: PageProps<"/[locale]/evaluation/example">) {
  if (!ENABLED || (await params).locale !== "en") notFound();
  return <EvaluationPage file={EVAL_EXAMPLE_FILE} title={TITLE} />;
}
