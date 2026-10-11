import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";
import { SearchView } from "@/components/search-view";
import { isSiteLocale } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { parseSearchQuery, toSearchParams, type RawParams } from "@/lib/filters";
import { searchNotifications } from "@/lib/search";

// Rendered on every request (SSR): the page reads its search parameters outside <Suspense>
// on purpose, so the complete result list is in the first HTML response.
export const instant = false;

export async function generateMetadata({ params }: PageProps<"/[locale]/search">): Promise<Metadata> {
  const { locale } = await params;
  if (!isSiteLocale(locale)) return {};
  const t = await getTranslations({ locale, namespace: "Search" });
  return {
    title: t("title"),
    description: t("metaDescription"),
    // Search result pages are not indexed (spec §9).
    robots: { index: false, follow: true },
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

export default async function SearchPage({ params, searchParams }: PageProps<"/[locale]/search">) {
  const { locale } = await params;
  // Search is not part of the Chinese module (spec §9).
  if (!isSiteLocale(locale)) notFound();
  const raw = await searchParams;
  const query = parseSearchQuery(raw);
  // One URL per search: the GET form also submits empty fields, `[]` names or unsorted
  // values; send those to the canonical URL so shared links stay short and stable.
  const canonical = toSearchParams(query).toString();
  if (received(raw).toString() !== canonical) {
    redirect(canonical ? `/${locale}/search?${canonical}` : `/${locale}/search`);
  }
  const response = await searchNotifications(getDb(), query, { locale });
  return <SearchView locale={locale} query={query} response={response} />;
}
