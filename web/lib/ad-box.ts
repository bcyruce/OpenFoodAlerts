/**
 * Where the SnelVink ad box may appear (spec §11.3 rule 3): at the bottom of the home page
 * (en, nl) and on the pages of the Chinese module (/zh/*). Never on the dashboard, search,
 * Notification detail, evaluation or data pages. Pure and client-safe: `<AdBox>` checks
 * the current pathname with it and renders nothing elsewhere.
 */

/** Home pages that carry the ad box. */
const HOME_LOCALES = ["en", "nl"];

/**
 * First path segments under /zh that are not part of the Chinese module: the shared
 * subscription flow, legal and data pages and the sections that 404 in zh. Every other
 * /zh page (the module, ticket 32) may show the ad box.
 */
const ZH_WITHOUT_AD = new Set([
  "alerts",
  "about",
  "privacy",
  "disclaimer",
  "colofon",
  "data",
  "dashboard",
  "search",
  "n",
  "evaluation",
]);

export function isAdBoxAllowed(pathname: string): boolean {
  const [locale, first, ...rest] = pathname.split("/").filter(Boolean);
  if (locale === undefined) return false;
  if (HOME_LOCALES.includes(locale)) return first === undefined && rest.length === 0;
  if (locale === "zh") return first === undefined || !ZH_WITHOUT_AD.has(first);
  return false;
}
