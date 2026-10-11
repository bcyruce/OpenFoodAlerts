"use client";

import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { FilterOption, LocalizedCatalog } from "@/lib/subscriptions/catalog";
import {
  SOURCE_CODES,
  SUBSCRIPTION_LOCALES,
  ZH_SOURCES,
  type SourceCode,
  type SubscriptionLocale,
} from "@/lib/subscriptions/validate";

const SOURCE_NAMES: Record<SourceCode, string> = { rasff: "RASFF", nvwa: "NVWA", openfda: "openFDA" };
const LOCALE_NAMES: Record<SubscriptionLocale, string> = { en: "English", nl: "Nederlands", zh: "中文" };
const LOCALE_LANG: Record<SubscriptionLocale, string> = { en: "en", nl: "nl", zh: "zh-Hans" };

type Status =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success"; email: string }
  | { kind: "error"; message: string };

type Props = {
  locale: SubscriptionLocale;
  catalog: LocalizedCatalog;
  consentText: string;
  consentTextVersion: string;
};

function toggle<T>(set: Set<T>, value: T, on: boolean): Set<T> {
  const next = new Set(set);
  if (on) next.add(value);
  else next.delete(value);
  return next;
}

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

function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="mt-1 text-sm font-medium text-red-800">
      {children}
    </p>
  );
}

/** The subscription form (spec §9 `/alerts`); posts JSON to /api/subscribe. */
export function SubscriptionForm({ locale, catalog, consentText, consentTextVersion }: Props) {
  const t = useTranslations("Alerts");
  const ids = useId();
  const [email, setEmail] = useState("");
  const [emailLocale, setEmailLocale] = useState<SubscriptionLocale>(locale);
  const [sources, setSources] = useState<Set<SourceCode>>(new Set(SOURCE_CODES));
  const [instant, setInstant] = useState<Set<SourceCode>>(new Set());
  const [hazards, setHazards] = useState<Set<number>>(new Set());
  const [products, setProducts] = useState<Set<number>>(new Set());
  const [countries, setCountries] = useState<Set<string>>(new Set());
  const [includeUnclassified, setIncludeUnclassified] = useState(true);
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const summaryRef = useRef<HTMLDivElement>(null);
  const successRef = useRef<HTMLHeadingElement>(null);

  // Chinese Subscriptions cover NVWA only (spec §10.1); the server checks this too.
  const zh = emailLocale === "zh";
  const allowed = (s: SourceCode) => !zh || ZH_SOURCES.includes(s);
  const effectiveSources = SOURCE_CODES.filter((s) => sources.has(s) && allowed(s));
  const effectiveInstant = effectiveSources.filter((s) => instant.has(s));

  function showErrors(fields: Set<string>, message: string) {
    setInvalid(fields);
    setStatus({ kind: "error", message });
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const fields = new Set<string>();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) fields.add("email");
    if (effectiveSources.length === 0) fields.add("filters.sources");
    if (!consent) fields.add("consent");
    if (fields.size > 0) return showErrors(fields, t("errorInvalid"));

    setInvalid(new Set());
    setStatus({ kind: "submitting" });
    try {
      const response = await fetch("/api/subscribe", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email,
          locale: emailLocale,
          filters: {
            sources: effectiveSources,
            hazard_categories: [...hazards],
            product_categories: [...products],
            origin_countries: [...countries],
          },
          include_unclassified: includeUnclassified,
          instant_sources: effectiveInstant,
          consent,
          consent_text_version: consentTextVersion,
          website,
        }),
      });
      if (response.status === 202) {
        setStatus({ kind: "success", email: email.trim() });
        requestAnimationFrame(() => successRef.current?.focus());
        return;
      }
      if (response.status === 429) return showErrors(new Set(), t("errorRateLimited"));
      if (response.status === 400) {
        const body = (await response.json()) as { fields?: { field: string }[] };
        const bad = new Set((body.fields ?? []).map((f) => f.field));
        if (bad.has("consent_text_version")) return showErrors(new Set(), t("errorOutdated"));
        return showErrors(bad, t("errorInvalid"));
      }
      showErrors(new Set(), t("errorServer"));
    } catch {
      showErrors(new Set(), t("errorServer"));
    }
  }

  if (status.kind === "success") {
    return (
      <div role="status" className="mt-6 rounded border border-green-700 bg-green-50 p-4">
        <h2 ref={successRef} tabIndex={-1} className="text-lg font-semibold">
          {t("successHeading")}
        </h2>
        <p className="mt-2">{t("success", { email: status.email })}</p>
      </div>
    );
  }

  const errorId = (field: string) => `${ids}-${field.replace(/\W/g, "-")}-error`;
  const describedBy = (field: string, ...others: string[]) =>
    [invalid.has(field) ? errorId(field) : null, ...others].filter(Boolean).join(" ") || undefined;

  return (
    <form onSubmit={submit} noValidate className="mt-6 space-y-6" data-testid="subscription-form">
      <div ref={summaryRef} tabIndex={-1} aria-live="assertive" className="outline-none">
        {status.kind === "error" && (
          <p className="rounded border border-red-800 bg-red-50 p-3 font-medium text-red-900">
            {status.message}
          </p>
        )}
      </div>

      <div>
        <label htmlFor={`${ids}-email`} className="block font-medium">
          {t("emailLabel")}
        </label>
        <input
          id={`${ids}-email`}
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={invalid.has("email") || undefined}
          aria-describedby={describedBy("email")}
          className="mt-1 block w-full max-w-md rounded border border-slate-500 px-3 py-2"
        />
        {invalid.has("email") && <FieldError id={errorId("email")}>{t("errorEmail")}</FieldError>}
      </div>

      <fieldset>
        <legend className="font-medium">{t("languageLegend")}</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          {SUBSCRIPTION_LOCALES.map((l) => (
            <label key={l} className="flex items-center gap-2">
              <input
                type="radio"
                name="locale"
                value={l}
                checked={emailLocale === l}
                onChange={() => setEmailLocale(l)}
              />
              <span lang={LOCALE_LANG[l]}>{LOCALE_NAMES[l]}</span>
            </label>
          ))}
        </div>
        {zh && (
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
          {SOURCE_CODES.map((s) => {
            const enabled = allowed(s);
            const checked = enabled && sources.has(s);
            return (
              <li key={s} className="rounded border border-slate-200 p-3">
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    name="sources"
                    value={s}
                    className="mt-1"
                    checked={checked}
                    disabled={!enabled}
                    onChange={(e) => setSources(toggle(sources, s, e.target.checked))}
                  />
                  <span>
                    <span className="font-medium">{SOURCE_NAMES[s]}</span>{" "}
                    <span className="text-slate-700">— {t(`sourceDescriptions.${s}`)}</span>
                  </span>
                </label>
                <label className="ml-6 mt-2 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name="instant_sources"
                    value={s}
                    checked={checked && instant.has(s)}
                    disabled={!checked}
                    aria-label={t("instantFor", { source: SOURCE_NAMES[s] })}
                    aria-describedby={`${ids}-instant-hint`}
                    onChange={(e) => setInstant(toggle(instant, s, e.target.checked))}
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
          selected={hazards}
          onChange={setHazards}
        />
        <CheckboxGroup
          legend={t("productLegend")}
          hint={t("filterHint")}
          options={catalog.productCategories}
          selected={products}
          onChange={setProducts}
        />
        <CheckboxGroup
          legend={t("countryLegend")}
          hint={t("filterHint")}
          options={catalog.countries}
          selected={countries}
          onChange={setCountries}
          search={t("countrySearch")}
        />
      </div>

      <div>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            name="include_unclassified"
            className="mt-1"
            checked={includeUnclassified}
            onChange={(e) => setIncludeUnclassified(e.target.checked)}
            aria-describedby={`${ids}-unclassified-hint`}
          />
          <span className="font-medium">{t("unclassifiedLabel")}</span>
        </label>
        <p id={`${ids}-unclassified-hint`} className="ml-6 text-sm text-slate-700">
          {t("unclassifiedHint")}
        </p>
      </div>

      {/* Honeypot (spec §11.2): hidden from people and assistive technology. */}
      <div aria-hidden="true" className="absolute -left-[10000px] top-auto h-px w-px overflow-hidden">
        <label>
          {t("honeypotLabel")}
          <input
            type="text"
            name="website"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </label>
      </div>

      <div>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            name="consent"
            className="mt-1"
            required
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            aria-invalid={invalid.has("consent") || undefined}
            aria-describedby={describedBy("consent")}
          />
          <span>{consentText}</span>
        </label>
        {invalid.has("consent") && (
          <FieldError id={errorId("consent")}>{t("errorConsent")}</FieldError>
        )}
        <p className="ml-6 mt-2 text-sm text-slate-700">{t("privacyNote")}</p>
      </div>

      <button
        type="submit"
        disabled={status.kind === "submitting"}
        className="rounded bg-blue-700 px-5 py-2 font-semibold text-white hover:bg-blue-900 disabled:opacity-70"
      >
        {status.kind === "submitting" ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
