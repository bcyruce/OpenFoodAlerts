const TIME_ZONE = "Europe/Amsterdam";
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const INTL_LOCALE: Record<string, string> = { en: "en-GB", nl: "nl-NL" };

/** A date (YYYY-MM-DD, shown as is) or timestamp (shown in Amsterdam time). */
export function formatDate(locale: string, value: string, withTime = false): string {
  const dateOnly = DATE_ONLY.test(value);
  return new Intl.DateTimeFormat(INTL_LOCALE[locale] ?? locale, {
    dateStyle: "long",
    ...(withTime && !dateOnly ? { timeStyle: "short" } : {}),
    timeZone: dateOnly ? "UTC" : TIME_ZONE,
  }).format(new Date(dateOnly ? `${value}T00:00:00Z` : value));
}

/** A source_fields value as text: dates formatted, everything else stringified. */
export function formatValue(locale: string, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return DATE_ONLY.test(value) ? formatDate(locale, value) : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
