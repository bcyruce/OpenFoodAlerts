import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";
import { connection } from "next/server";
import { Dashboard } from "@/components/dashboard/dashboard";
import { isSiteLocale, SITE_LOCALES } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import type { RawParams } from "@/lib/filters";
import { getStats } from "@/lib/stats";
import { parseStatsQuery, toStatsParams } from "@/lib/stats-query";
import { localizeCatalog } from "@/lib/subscriptions/catalog";
import { loadFilterCatalog } from "@/lib/subscriptions/runtime";

// Rendered on every request (SSR): the statistics for the URL are in the first HTML
// response; the client takes over filtering afterwards.
export const instant = false;

export async function generateMetadata({ params }: PageProps<"/[locale]/dashboard">): Promise<Metadata> {
  const { locale } = await params;
  if (!isSiteLocale(locale)) return {};
  const t = await getTranslations({ locale, namespace: "Dashboard" });
  return {
    title: t("title"),
    description: t("metaDescription"),
    // Filtered views point to the unfiltered dashboard.
    alternates: {
      canonical: `/${locale}/dashboard`,
      languages: Object.fromEntries(SITE_LOCALES.map((l) => [l, `/${l}/dashboard`])),
    },
  };
}

function received(params: RawParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    for (const v of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      out.append(name, v);
    }
  }
  return out;
}

export default async function DashboardPage({ params, searchParams }: PageProps<"/[locale]/dashboard">) {
  const { locale } = await params;
  // The dashboard is not part of the Chinese module (spec §9).
  if (!isSiteLocale(locale)) notFound();
  const raw = await searchParams;
  const query = parseStatsQuery(raw);
  // One URL per view: the no-JavaScript form submits empty fields, and `[]` names or
  // unsorted values are accepted; send those to the canonical URL.
  const canonical = toStatsParams(query).toString();
  if (received(raw).toString() !== canonical) {
    redirect(canonical ? `/${locale}/dashboard?${canonical}` : `/${locale}/dashboard`);
  }
  // The default period is relative to today: render at request time.
  await connection();
  const [stats, catalog, messages, t] = await Promise.all([
    getStats(getDb(), query, { locale }),
    loadFilterCatalog(),
    getMessages({ locale }),
    getTranslations({ locale, namespace: "Dashboard" }),
  ]);
  return (
    <>
      <h1 className="text-3xl font-semibold text-slate-900">{t("title")}</h1>
      <p className="mt-2 max-w-prose text-slate-700">{t("intro")}</p>
      <NextIntlClientProvider locale={locale} messages={{ Dashboard: messages.Dashboard }}>
        <Dashboard
          locale={locale}
          initialQuery={query}
          initialStats={stats}
          catalog={localizeCatalog(catalog, locale)}
        />
      </NextIntlClientProvider>
    </>
  );
}
