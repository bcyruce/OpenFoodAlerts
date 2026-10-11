import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["en", "nl", "zh"],
  defaultLocale: "en",
  localePrefix: "always",
  // No cookies on this site (spec §11.1 #8); hreflang links come from page metadata.
  localeCookie: false,
  alternateLinks: false,
});

export type Locale = (typeof routing.locales)[number];

/**
 * en and nl cover the whole site. zh exists only for the Chinese module, the subscription
 * flow and the legal pages (spec §9); every other page returns 404 under /zh. Pages that
 * are not available in zh call `notFound()` when `!isSiteLocale(locale)`.
 */
export const SITE_LOCALES = ["en", "nl"] as const satisfies readonly Locale[];

export function isSiteLocale(locale: string): locale is (typeof SITE_LOCALES)[number] {
  return (SITE_LOCALES as readonly string[]).includes(locale);
}

/** First path segments (after the locale) that also exist in zh. */
const ZH_SECTIONS = ["alerts"];

/** The locales a page exists in, from its path without the locale (e.g. "alerts/confirm"). */
export function localesForPath(rest: string): readonly Locale[] {
  return ZH_SECTIONS.includes(rest.split("/")[0]) ? routing.locales : SITE_LOCALES;
}

/** `lang` attribute values; Chinese pages are Simplified Chinese (spec §9). */
export const HTML_LANG: Record<Locale, string> = { en: "en", nl: "nl", zh: "zh-Hans" };

/** Where the site name links to. zh has no home page until the Chinese module (ticket 32). */
export function homePath(locale: Locale): string {
  return locale === "zh" ? "/zh/alerts" : `/${locale}`;
}
