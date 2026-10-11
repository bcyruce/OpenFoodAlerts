/**
 * The values a Subscription can filter on (spec §10.1), from the RASFF seed tables:
 * Hazard categories and Product categories by RASFF id, countries of origin by ISO code.
 */
import { asc, sql } from "drizzle-orm";
import { countries, hazardCategories, productCategories } from "@/db/generated/schema";
import type { Reader } from "@/lib/notifications";
import type { KnownFilterValues, SubscriptionLocale } from "./validate";

type Names = { nameEn: string; nameNl: string | null; nameZh: string | null };

export type FilterCatalog = {
  hazardCategories: ({ rasffId: number } & Names)[];
  productCategories: ({ rasffId: number } & Names)[];
  /** Real countries only (two-letter codes); RASFF also lists organisations such as ECDC. */
  countries: ({ iso2: string } & Names)[];
};

export type FilterOption<T> = { value: T; label: string };

export type LocalizedCatalog = {
  hazardCategories: FilterOption<number>[];
  productCategories: FilterOption<number>[];
  countries: FilterOption<string>[];
};

export async function getFilterCatalog(db: Reader): Promise<FilterCatalog> {
  const names = { nameEn: sql<string>`name_en`, nameNl: sql<string | null>`name_nl`, nameZh: sql<string | null>`name_zh` };
  const [hazards, products, countryRows] = await Promise.all([
    db.select({ rasffId: hazardCategories.rasffId, ...names }).from(hazardCategories).orderBy(asc(hazardCategories.rasffId)),
    db.select({ rasffId: productCategories.rasffId, ...names }).from(productCategories).orderBy(asc(productCategories.rasffId)),
    db
      .select({ iso2: countries.iso2, ...names })
      .from(countries)
      .where(sql`${countries.iso2} ~ '^[A-Z]{2}$'`)
      .orderBy(asc(countries.iso2)),
  ]);
  return { hazardCategories: hazards, productCategories: products, countries: countryRows };
}

export function knownFilterValues(catalog: FilterCatalog): KnownFilterValues {
  return {
    hazardCategories: catalog.hazardCategories.map((h) => h.rasffId),
    productCategories: catalog.productCategories.map((p) => p.rasffId),
    countries: catalog.countries.map((c) => c.iso2),
  };
}

function localName(names: Names, locale: SubscriptionLocale): string {
  const local = locale === "nl" ? names.nameNl : locale === "zh" ? names.nameZh : names.nameEn;
  return local ?? names.nameEn;
}

/**
 * Labels in the page language, sorted for that language. Category names fall back to
 * English (the seed has no translations yet); country names come from the seed or else
 * from the runtime's CLDR data.
 */
export function localizeCatalog(catalog: FilterCatalog, locale: SubscriptionLocale): LocalizedCatalog {
  const collator = new Intl.Collator(locale);
  const regions = new Intl.DisplayNames([locale === "zh" ? "zh-Hans" : locale], {
    type: "region",
    fallback: "none",
  });
  const sorted = <T>(options: FilterOption<T>[]) =>
    options.sort((a, b) => collator.compare(a.label, b.label));
  return {
    hazardCategories: sorted(
      catalog.hazardCategories.map((h) => ({ value: h.rasffId, label: localName(h, locale) })),
    ),
    productCategories: sorted(
      catalog.productCategories.map((p) => ({ value: p.rasffId, label: localName(p, locale) })),
    ),
    countries: sorted(
      catalog.countries.map((c) => {
        const seeded = locale === "en" ? null : locale === "nl" ? c.nameNl : c.nameZh;
        const label = seeded ?? (locale === "en" ? c.nameEn : (regions.of(c.iso2) ?? c.nameEn));
        return { value: c.iso2, label };
      }),
    ),
  };
}
