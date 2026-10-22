import { getTranslations } from "next-intl/server";
import { deployedEvalReport, promptNumber, testAccuracy } from "@/lib/ai-badge";
import type { AiProvenance } from "@/lib/ai";
import { formatDate } from "@/lib/format";
import type { AiBadgeProps } from "./ai-badge";

/**
 * Server-side: a function that writes the badge of an AI value in `locale` (spec §9
 * wording), quoting the deployed latest.json. Built once per page, used for every badge.
 */
export async function aiBadgeWriter(
  locale: string,
): Promise<(made: AiProvenance, sourceUrl: string) => AiBadgeProps> {
  const t = await getTranslations({ locale, namespace: "Ai" });
  const report = deployedEvalReport();
  const percent = new Intl.NumberFormat(locale === "zh" ? "zh-Hans" : locale, {
    style: "percent",
    maximumFractionDigits: 1,
  });
  return (made, sourceUrl) => {
    const summary = made.task === "t6_summary";
    const accuracy = summary ? null : testAccuracy(report, made);
    const facts = { model: made.model, date: formatDate(locale, made.createdAt), prompt: promptNumber(made.promptVersion) };
    const description = [
      made.reviewed ? t("reviewed") : null,
      summary ? t("summarisedBy", facts) : t("classifiedBy", facts),
      summary
        ? t("summaryNotScored")
        : accuracy === null
          ? t("notEvaluated")
          : t("accuracy", { accuracy: percent.format(accuracy) }),
      t("officialPrevails"),
    ]
      .filter(Boolean)
      .join(" ");
    return {
      reviewed: made.reviewed,
      text: made.reviewed ? t("reviewedBadge") : t("badge"),
      suffix: made.reviewed ? t("reviewedBadgeSuffix") : t("badgeSuffix"),
      description,
      links: [
        { href: sourceUrl, text: t("officialSource"), external: true },
        // /evaluation exists in English only (spec §9).
        { href: "/en/evaluation", text: t("evaluation"), hrefLang: locale === "en" ? undefined : "en" },
      ],
    };
  };
}
