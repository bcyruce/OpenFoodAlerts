/**
 * Building blocks for the legal texts in this folder. The texts themselves are per-locale
 * JSX (one component per locale and page), not messages: they are long, structured and
 * read best as whole documents when the owner reviews a translation.
 */
import type { ReactNode } from "react";
import type { Locale } from "@/i18n/routing";
import { OPERATOR } from "@/lib/legal";

const TODO_TEXT: Record<Locale, string> = {
  en: "[to be added before launch]",
  nl: "[wordt vóór de lancering aangevuld]",
  zh: "[上线前补充]",
};

/** Visible placeholder for a fact the owner has not supplied yet (lib/legal.ts). */
export function Todo({ locale }: { locale: Locale }) {
  return (
    <mark data-testid="legal-todo" className="bg-amber-100 px-1 text-slate-900">
      {TODO_TEXT[locale]}
    </mark>
  );
}

/** A value from the legal configuration, or the placeholder while it is unknown. */
export function Value({ value, locale }: { value: string | null; locale: Locale }) {
  return value === null ? <Todo locale={locale} /> : <>{value}</>;
}

export function Address({ locale }: { locale: Locale }) {
  if (OPERATOR.address === null) return <Todo locale={locale} />;
  return (
    <>
      {OPERATOR.address.map((line) => (
        <span key={line} className="block">
          {line}
        </span>
      ))}
    </>
  );
}

export function Email({ locale }: { locale: Locale }) {
  if (OPERATOR.email === null) return <Todo locale={locale} />;
  return <a href={`mailto:${OPERATOR.email}`}>{OPERATOR.email}</a>;
}

/** The operator's name as used in running text: "{legal name}, trading as OpenFoodAlerts". */
export function OperatorName({ locale }: { locale: Locale }) {
  return <Value value={OPERATOR.legalName} locale={locale} />;
}

export function OwnerName({ locale }: { locale: Locale }) {
  return <Value value={OPERATOR.ownerName} locale={locale} />;
}

export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} rel="noopener">
      {children}
    </a>
  );
}
