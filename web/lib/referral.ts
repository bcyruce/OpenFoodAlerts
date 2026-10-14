/**
 * Links to SnelVink, the maker's company (spec §11.3): the footer attribution, the About
 * page disclosure and the ad box. Every link carries the UTM parameters of rule 7 so that
 * clicks can be counted (goal G3); nothing else about the visitor is passed on.
 */

/** Where a SnelVink link sits; the UTM medium of spec §11.3 rule 7. */
export type ReferralMedium = "footer" | "about" | "home_box" | "zh_box";

/** SnelVink's site. OWNER TODO: confirm the address (default is a guess). */
export const SNELVINK_URL = process.env.SNELVINK_URL || "https://snelvink.nl";

/**
 * The maintainer's name for "Built by …, founder of SnelVink". OWNER TODO: set OWNER_NAME;
 * until then the footer shows a localized placeholder.
 */
export const OWNER_NAME = process.env.OWNER_NAME;

export function snelvinkUrl(medium: ReferralMedium, base: string = SNELVINK_URL): string {
  const url = new URL(base);
  url.searchParams.set("utm_source", "openfoodalerts.nl");
  url.searchParams.set("utm_medium", medium);
  url.searchParams.set("utm_campaign", "v1");
  return url.toString();
}

export function ownerName(configured: string | undefined, placeholder: string): string {
  return configured?.trim() || placeholder;
}
