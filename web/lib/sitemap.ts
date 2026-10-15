/**
 * `/sitemap.xml` entries (spec §9): the indexable pages with hreflang alternates. Search
 * and the subscription pages are `noindex` and left out. Pure; `app/sitemap.ts` loads the
 * Notifications.
 */
import type { MetadataRoute } from "next";
import { ZH_HOME, ZH_PAGES } from "@/content/zh";
import { HTML_LANG, routing, SITE_LOCALES, type Locale } from "@/i18n/routing";
import { notificationPath } from "./notification-path";

/** Notification detail pages listed in the sitemap, most recently published first. */
export const SITEMAP_NOTIFICATIONS = 5000;

export type SitemapNotification = { source: string; key: string; lastChangedAt: string };

/** A page of the Chinese module (zh only) with its review date; `null` = draft. */
export type ZhSitemapPage = { path: string; reviewedOn: string | null };

/** `/zh` and the guide pages from `content/zh`. */
export function zhSitemapPages(): ZhSitemapPage[] {
  return [
    { path: "/zh", reviewedOn: ZH_HOME.reviewedOn },
    ...Object.entries(ZH_PAGES).map(([slug, page]) => ({ path: `/zh/${slug}`, reviewedOn: page.reviewedOn })),
  ];
}

/** Static pages, by path without the locale, with the locales they exist in. */
const PAGES: { path: string; locales: readonly Locale[] }[] = [
  { path: "", locales: SITE_LOCALES },
  { path: "/dashboard", locales: SITE_LOCALES },
  // Data and legal pages: ticket 27 (spec §9: /data in English only).
  { path: "/data", locales: ["en"] },
  ...["/about", "/privacy", "/disclaimer", "/colofon"].map((path) => ({
    path,
    locales: routing.locales,
  })),
];

function localized(
  locales: readonly Locale[],
  url: (locale: Locale) => string,
  extra: { lastModified?: string } = {},
): MetadataRoute.Sitemap {
  const alternates =
    locales.length > 1
      ? { alternates: { languages: Object.fromEntries(locales.map((l) => [HTML_LANG[l], url(l)])) } }
      : {};
  return locales.map((locale) => ({ url: url(locale), ...extra, ...alternates }));
}

/**
 * The Chinese module pages are listed once reviewed, with `lastModified` = the review date;
 * drafts are `noindex` and left out.
 */
export function buildSitemap(
  siteUrl: string,
  notifications: SitemapNotification[],
  zhPages: ZhSitemapPage[] = zhSitemapPages(),
): MetadataRoute.Sitemap {
  return [
    ...PAGES.flatMap(({ path, locales }) => localized(locales, (l) => `${siteUrl}/${l}${path}`)),
    ...zhPages.flatMap(({ path, reviewedOn }) =>
      reviewedOn === null ? [] : [{ url: `${siteUrl}${path}`, lastModified: reviewedOn }],
    ),
    ...notifications.flatMap((n) =>
      localized(SITE_LOCALES, (l) => `${siteUrl}${notificationPath(l, n.source, n.key)}`, {
        lastModified: n.lastChangedAt,
      }),
    ),
  ];
}
