"use client";

// The filter, language and Instant email fields shared by the subscription form (/alerts)
// and the manage page (/alerts/manage/[token]). Strings come from the `Alerts` namespace.
import { useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
import type { FilterOption, LocalizedCatalog } from "@/lib/subscriptions/catalog";
import {
  SOURCE_CODES,
  SUBSCRIPTION_LOCALES,
  ZH_SOURCES,
  type SourceCode,
  type SubscriptionLocale,
  type SubscriptionSettings,
} from "@/lib/subscriptions/validate";

export const SOURCE_NAMES: Record<SourceCode, string> = { rasff: "RASFF", nvwa: "NVWA", openfda: "openFDA" };
const LOCALE_NAMES: Record<SubscriptionLocale, string> = { en: "English", nl: "Nederlands", zh: "中文" };
const LOCALE_LANG: Record<SubscriptionLocale, string> = { en: "en", nl: "nl", zh: "zh-Hans" };

function toggle<T>(set: Set<T>, value: T, on: boolean): Set<T> {
  const next = new Set(set);
  if (on) next.add(value);
  else next.delete(value);
  return next;
}

/** Ids and aria attributes for fields that can show an error. */
export function fieldErrors(ids: string, invalid: Set<string>) {
  const errorId = (field: string) => `${ids}-${field.replace(/\W/g, "-")}-error`;
  const describedBy = (field: string, ...others: string[]) =>
    [invalid.has(field) ? errorId(field) : null, ...others].filter(Boolean).join(" ") || undefined;
  return { errorId, describedBy };
}

export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="mt-1 text-sm font-medium text-red-800">
      {children}
    </p>
  );
}

/** State of the shared fields. An empty `sources` filter (no restriction) shows all ticked. */
export function useSubscriptionSettings(initial: SubscriptionSettings) {
  const [locale, setLocale] = useState<SubscriptionLocale>(initial.locale);
  const [sources, setSources] = useState<Set<SourceCode>>(
    new Set(initial.filters.sources.length > 0 ? initial.filters.sources : SOURCE_CODES),
  );
  const [instant, setInstant] = useState<Set<SourceCode>>(new Set(initial.instantSources));
  const [hazards, setHazards] = useState<Set<number>>(new Set(initial.filters.hazard_categories));
  const [products, setProducts] = useState<Set<number>>(new Set(initial.filters.product_categories));
  const [countries, setCountries] = useState<Set<string>>(new Set(initial.filters.origin_countries));
  const [includeUnclassified, setIncludeUnclassified] = useState(initial.includeUnclassified);

  // Chinese Subscriptions cover NVWA only (spec §10.1); the server checks this too.
  const allowed = (s: SourceCode) => locale !== "zh" || ZH_SOURCES.includes(s);
  const effectiveSources = SOURCE_CODES.filter((s) => sources.has(s) && allowed(s));
  const effectiveInstant = effectiveSources.filter((s) => instant.has(s));

  return {
    locale,
    setLocale,
    sources,
    setSources,
    instant,
    setInstant,
    hazards,
    setHazards,
    products,
    setProducts,
    countries,
    setCountries,
    includeUnclassified,
    setIncludeUnclassified,
    allowed,
    effectiveSources,
    /** The request body fields, as /api/subscribe and /api/manage expect them. */
    body: () => ({
      locale,
      filters: {
        sources: effectiveSources,
        hazard_categories: [...hazards],
        product_categories: [...products],
        origin_countries: [...countries],
      },
      include_unclassified: includeUnclassified,
      instant_sources: effectiveInstant,
    }),
  };
}

export type SettingsState = ReturnType<typeof useSubscriptionSettings>;

function CheckboxGroup<T extends string | number>({
  legend,
  hint,
  options,
  selected,
  onChange,
  search,
}: {
  legend: string;
  hint: string;
  options: FilterOption<T>[];
  selected: Set<T>;
  onChange: (next: Set<T>) => void;
  search?: string;
}) {
  const t = useTranslations("Alerts");
  const [query, setQuery] = useState("");
  const searchId = useId();
  const q = query.trim().toLocaleLowerCase();
  return (
    <details className="rounded border border-slate-300 p-3">
      <summary className="cursor-pointer font-medium">
        {legend} <span className="font-normal text-slate-700">({t("selectedCount", { count: selected.size })})</span>
      </summary>
      <fieldset className="mt-3">
        <legend className="sr-only">{legend}</legend>
        <p className="text-sm text-slate-700">{hint}</p>
        {search && (
          <div className="mt-2">
            <label htmlFor={searchId} className="text-sm font-medium">
              {search}
            </label>
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="mt-1 block w-full max-w-xs rounded border border-slate-500 px-2 py-1"
            />
          </div>
        )}
        <ul className="mt-2 grid max-h-72 gap-1 overflow-y-auto sm:grid-cols-2">
          {options.map((option) => (
            <li key={option.value} hidden={q !== "" && !option.label.toLocaleLowerCase().includes(q)}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.has(option.value)}
                  onChange={(e) => onChange(toggle(selected, option.value, e.target.checked))}
                />
                <span>{option.label}</span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
    </details>
  );
}

/** Email language, Sources with Instant email, filter groups and "include unclassified". */
export function SubscriptionSettingsFields({
  settings: s,
  catalog,
  ids,
  invalid,
}: {
  settings: SettingsState;
  catalog: LocalizedCatalog;
  /** From `useId()` of the surrounding form. */
  ids: string;
  invalid: Set<string>;
}) {
  const t = useTranslations("Alerts");
  const { errorId, describedBy } = fieldErrors(ids, invalid);
  return (
    <>
      <fieldset>
        <legend className="font-medium">{t("languageLegend")}</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          {SUBSCRIPTION_LOCALES.map((l) => (
            <label key={l} className="flex items-center gap-2">
              <input
                type="radio"
                name="locale"
                value={l}
                checked={s.locale === l}
                onChange={() => s.setLocale(l)}
              />
              <span lang={LOCALE_LANG[l]}>{LOCALE_NAMES[l]}</span>
            </label>
          ))}
        </div>
        {s.locale === "zh" && (
          <p className="mt-2 text-sm text-slate-700" data-testid="zh-note">
            {t("languageZhNote")}
          </p>
        )}
      </fieldset>

      <fieldset aria-describedby={describedBy("filters.sources", `${ids}-sources-hint`)}>
        <legend className="font-medium">{t("sourcesLegend")}</legend>
        <p id={`${ids}-sources-hint`} className="text-sm text-slate-700">
          {t("sourcesHint")}
        </p>
        {invalid.has("filters.sources") && (
          <FieldError id={errorId("filters.sources")}>{t("errorSources")}</FieldError>
        )}
        <ul className="mt-2 space-y-3">
          {SOURCE_CODES.map((source) => {
            const enabled = s.allowed(source);
            const checked = enabled && s.sources.has(source);
            return (
              <li key={source} className="rounded border border-slate-200 p-3">
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    name="sources"
                    value={source}
                    className="mt-1"
                    checked={checked}
                    disabled={!enabled}
                    onChange={(e) => s.setSources(toggle(s.sources, source, e.target.checked))}
                  />
                  <span>
                    <span className="font-medium">{SOURCE_NAMES[source]}</span>{" "}
                    <span className="text-slate-700">— {t(`sourceDescriptions.${source}`)}</span>
                  </span>
                </label>
                <label className="ml-6 mt-2 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="instant_sources"
                    value={source}
                    checked={checked && s.instant.has(source)}
                    disabled={!checked}
                    aria-label={t("instantFor", { source: SOURCE_NAMES[source] })}
                    aria-describedby={`${ids}-instant-hint`}
                    onChange={(e) => s.setInstant(toggle(s.instant, source, e.target.checked))}
                  />
                  <span aria-hidden="true">{t("instantLabel")}</span>
                </label>
              </li>
            );
          })}
        </ul>
        <p id={`${ids}-instant-hint`} className="mt-2 text-sm text-slate-700">
          {t("instantHint")}
        </p>
      </fieldset>

      <div className="space-y-3">
        <CheckboxGroup
          legend={t("hazardLegend")}
          hint={t("filterHint")}
          options={catalog.hazardCategories}
          selected={s.hazards}
          onChange={s.setHazards}
        />
        <CheckboxGroup
          legend={t("productLegend")}
          hint={t("filterHint")}
          options={catalog.productCategories}
          selected={s.products}
          onChange={s.setProducts}
        />
        <CheckboxGroup
          legend={t("countryLegend")}
          hint={t("filterHint")}
          options={catalog.countries}
          selected={s.countries}
          onChange={s.setCountries}
          search={t("countrySearch")}
        />
      </div>

      <div>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            name="include_unclassified"
            className="mt-1"
            checked={s.includeUnclassified}
            onChange={(e) => s.setIncludeUnclassified(e.target.checked)}
            aria-describedby={`${ids}-unclassified-hint`}
          />
          <span className="font-medium">{t("unclassifiedLabel")}</span>
        </label>
        <p id={`${ids}-unclassified-hint`} className="ml-6 text-sm text-slate-700">
          {t("unclassifiedHint")}
        </p>
      </div>
    </>
  );
}
