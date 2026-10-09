/** Public site settings, read at build time. */

export const SITE_URL = (process.env.SITE_URL ?? "https://openfoodalerts.nl").replace(/\/$/, "");

/** Public repository; "report an error" opens an issue there. */
export const REPO_URL = (
  process.env.OFA_REPO_URL ?? "https://github.com/bcyruce/OpenFoodAlerts"
).replace(/\/$/, "");

export const OG_LOCALES: Record<string, string> = { en: "en_GB", nl: "nl_NL" };

/** GitHub "new issue" link, prefilled with the page that has the error. */
export function reportErrorUrl(pageUrl: string, subject: string): string {
  const params = new URLSearchParams({
    title: `Data error: ${subject}`,
    body: `Page: ${pageUrl}\n\nWhat is wrong, and where did you see the correct information?\n`,
    labels: "data-error",
  });
  return `${REPO_URL}/issues/new?${params.toString()}`;
}
