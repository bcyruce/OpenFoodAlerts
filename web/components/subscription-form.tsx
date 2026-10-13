"use client";

import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent } from "react";
import {
  FieldError,
  fieldErrors,
  SubscriptionSettingsFields,
  useSubscriptionSettings,
} from "@/components/subscription-settings";
import type { LocalizedCatalog } from "@/lib/subscriptions/catalog";
import type { SubscriptionLocale } from "@/lib/subscriptions/validate";

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

/** The subscription form (spec §9 `/alerts`); posts JSON to /api/subscribe. */
export function SubscriptionForm({ locale, catalog, consentText, consentTextVersion }: Props) {
  const t = useTranslations("Alerts");
  const ids = useId();
  const [email, setEmail] = useState("");
  const settings = useSubscriptionSettings({
    locale,
    filters: { sources: [], hazard_categories: [], product_categories: [], origin_countries: [] },
    includeUnclassified: true,
    instantSources: [],
  });
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const summaryRef = useRef<HTMLDivElement>(null);
  const successRef = useRef<HTMLHeadingElement>(null);

  function showErrors(fields: Set<string>, message: string) {
    setInvalid(fields);
    setStatus({ kind: "error", message });
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const fields = new Set<string>();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) fields.add("email");
    if (settings.effectiveSources.length === 0) fields.add("filters.sources");
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
          ...settings.body(),
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

  const { errorId, describedBy } = fieldErrors(ids, invalid);

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

      <SubscriptionSettingsFields settings={settings} catalog={catalog} ids={ids} invalid={invalid} />

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
