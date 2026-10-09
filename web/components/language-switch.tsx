"use client";

import { usePathname } from "next/navigation";

const NAMES: Record<string, string> = { en: "English", nl: "Nederlands" };

/** Links to the current page in each locale (the locale is the first path segment). */
export function LanguageSwitch({
  label,
  locales,
  current,
}: {
  label: string;
  locales: readonly string[];
  current: string;
}) {
  const pathname = usePathname() ?? `/${current}`;
  const rest = pathname.split("/").slice(2).join("/");
  return (
    <nav aria-label={label}>
      <ul className="flex gap-3 text-sm">
        {locales.map((locale) => (
          <li key={locale}>
            {locale === current ? (
              <span aria-current="true" className="font-semibold text-slate-900">
                {NAMES[locale] ?? locale}
              </span>
            ) : (
              <a href={`/${locale}${rest ? `/${rest}` : ""}`} hrefLang={locale} lang={locale}>
                {NAMES[locale] ?? locale}
              </a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
