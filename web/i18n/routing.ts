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
const ZH_SECTIONS = ["alerts", "about", "privacy", "disclaimer", "colofon"];

/**
 * First path segments that exist only in English (spec §9: `/data`, `/evaluation`).
 * `/nl/…` and `/zh/…` redirect to `/en/…` (next.config.ts).
 */
export const EN_ONLY_SECTIONS = ["data", "evaluation"];

/** The guide pages of the Chinese module (ticket 32): they exist only in zh. */
export const ZH_MODULE_PAGES = ["nvwa-jiancha", "zhaohui-jinggao", "jiancha-jieguo-gongkai", "jinkou"] as const;

export type ZhModulePage = (typeof ZH_MODULE_PAGES)[number];

/**
 * The Chinese module's NVWA warning stream (ticket 33): zh only, ISR, AI summaries; not a
 * written guide page, so it has no entry in `content/zh`. Pages 2… are `/zh/jinggao/{n}`.
 */
export const ZH_WARNINGS_PAGE = "jinggao";

/**
 * The locales a page exists in, from its path without the locale (e.g. "alerts/confirm").
 * Every locale has a home page (`/zh` is the Chinese module's landing page).
 */
export function localesForPath(rest: string): readonly Locale[] {
  const section = rest.split("/")[0];
  if (section === "") return routing.locales;
  if (EN_ONLY_SECTIONS.includes(section)) return ["en"];
  if ((ZH_MODULE_PAGES as readonly string[]).includes(section) || section === ZH_WARNINGS_PAGE) {
    return ["zh"];
  }
  return ZH_SECTIONS.includes(section) ? routing.locales : SITE_LOCALES;
}

/** `lang` attribute values; Chinese pages are Simplified Chinese (spec §9). */
export const HTML_LANG: Record<Locale, string> = { en: "en", nl: "nl", zh: "zh-Hans" };

/** Where the site name links to: the home page, for zh the Chinese module (`/zh`). */
export function homePath(locale: Locale): string {
  return `/${locale}`;
}
