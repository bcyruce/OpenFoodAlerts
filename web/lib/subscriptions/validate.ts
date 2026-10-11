/**
 * Validation of the `/api/subscribe` body (spec §8, §10.1). Pure: the known category and
 * country values are passed in, so the same rules run in tests, the API and the form.
 */
import { CONSENT_TEXT_VERSION } from "./consent";

export const SOURCE_CODES = ["rasff", "nvwa", "openfda"] as const;
export type SourceCode = (typeof SOURCE_CODES)[number];

export const SUBSCRIPTION_LOCALES = ["en", "nl", "zh"] as const;
export type SubscriptionLocale = (typeof SUBSCRIPTION_LOCALES)[number];

/** Chinese Subscriptions cover NVWA only (spec §10.1). */
export const ZH_SOURCES: readonly SourceCode[] = ["nvwa"];

/** Stored as `subscriptions.filters`; an empty array means no restriction. */
export type SubscriptionFilters = {
  sources: SourceCode[];
  /** RASFF dictionary ids (`hazard_categories.rasff_id`). */
  hazard_categories: number[];
  /** RASFF dictionary ids (`product_categories.rasff_id`). */
  product_categories: number[];
  /** `countries.iso2` */
  origin_countries: string[];
};

export type SubscriptionRequest = {
  /** Normalized (trimmed, lowercased). */
  email: string;
  locale: SubscriptionLocale;
  filters: SubscriptionFilters;
  includeUnclassified: boolean;
  /** Sorted; a subset of `filters.sources` (or of all Sources when that is empty). */
  instantSources: SourceCode[];
  consentTextVersion: string;
};

export type KnownFilterValues = {
  hazardCategories: readonly number[];
  productCategories: readonly number[];
  countries: readonly string[];
};

export type FieldError = { field: string; code: string };

export type ParseResult =
  | { ok: true; value: SubscriptionRequest }
  | { ok: false; errors: FieldError[] };

const MAX_EMAIL_LENGTH = 254;
const EMAIL_PATTERN = /^[^\s@]{1,64}@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A sorted, de-duplicated list of allowed values, or null if anything is not allowed. */
function pickList<T extends string | number>(
  value: unknown,
  allowed: ReadonlySet<T>,
): T[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > allowed.size) return null;
  if (!value.every((v) => allowed.has(v as T))) return null;
  return [...new Set(value as T[])].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

export function parseSubscriptionRequest(raw: unknown, known: KnownFilterValues): ParseResult {
  if (!isRecord(raw)) return { ok: false, errors: [{ field: "body", code: "invalid" }] };
  const errors: FieldError[] = [];
  const fail = (field: string, code = "invalid") => errors.push({ field, code });

  const email = typeof raw.email === "string" ? normalizeEmail(raw.email) : "";
  if (email.length > MAX_EMAIL_LENGTH || !EMAIL_PATTERN.test(email)) fail("email");

  const locale = raw.locale as SubscriptionLocale;
  if (!SUBSCRIPTION_LOCALES.includes(locale)) fail("locale");

  const rawFilters = raw.filters === undefined ? {} : raw.filters;
  const filters = isRecord(rawFilters) ? rawFilters : null;
  if (!filters) fail("filters");
  const sources = pickList(filters?.sources, new Set(SOURCE_CODES));
  const hazards = pickList(filters?.hazard_categories, new Set(known.hazardCategories));
  const products = pickList(filters?.product_categories, new Set(known.productCategories));
  const countries = pickList(filters?.origin_countries, new Set(known.countries));
  if (filters) {
    if (!sources) fail("filters.sources");
    else if (locale === "zh" && sources.join() !== ZH_SOURCES.join()) {
      fail("filters.sources", "zh_nvwa_only");
    }
    if (!hazards) fail("filters.hazard_categories");
    if (!products) fail("filters.product_categories");
    if (!countries) fail("filters.origin_countries");
  }

  const includeUnclassified = raw.include_unclassified ?? true;
  if (typeof includeUnclassified !== "boolean") fail("include_unclassified");

  const chosen = sources && sources.length > 0 ? sources : SOURCE_CODES;
  const instant = pickList(raw.instant_sources, new Set<SourceCode>(SOURCE_CODES));
  if (!instant) fail("instant_sources");
  else if (!instant.every((s) => chosen.includes(s))) fail("instant_sources", "not_in_sources");

  if (raw.consent !== true) fail("consent", "required");
  if (raw.consent_text_version !== CONSENT_TEXT_VERSION) fail("consent_text_version", "outdated");

  if (errors.length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      email,
      locale,
      filters: {
        sources: sources!,
        hazard_categories: hazards!,
        product_categories: products!,
        origin_countries: countries!,
      },
      includeUnclassified: includeUnclassified as boolean,
      instantSources: instant!,
      consentTextVersion: CONSENT_TEXT_VERSION,
    },
  };
}
