import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { Prose } from "@/components/prose";
import { HTML_LANG, routing, type Locale } from "@/i18n/routing";
import { formatDate } from "@/lib/format";
import { LEGAL_TEXTS_VERSION } from "@/lib/legal";

/** The static pages of spec §9 that exist in en, nl and zh. */
export type LegalPageName = "about" | "privacy" | "disclaimer" | "colofon";

export async function legalMetadata(page: LegalPageName, locale: Locale): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: `Legal.${page}` });
  return {
    title: t("title"),
    description: t("description"),
    alternates: {
      canonical: `/${locale}/${page}`,
      languages: Object.fromEntries(routing.locales.map((l) => [HTML_LANG[l], `/${l}/${page}`])),
    },
  };
}

export async function LegalPage({
  page,
  locale,
  children,
}: {
  page: LegalPageName;
  locale: Locale;
  children: ReactNode;
}) {
  const t = await getTranslations({ locale, namespace: "Legal" });
  return (
    <article>
      <h1 className="text-3xl font-semibold text-slate-900">{t(`${page}.title`)}</h1>
      <p className="mt-2 text-sm text-slate-700">
        {t("updated", { date: formatDate(locale, LEGAL_TEXTS_VERSION) })}
      </p>
      <Prose>{children}</Prose>
    </article>
  );
}
