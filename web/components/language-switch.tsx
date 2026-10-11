"use client";

import { usePathname } from "next/navigation";
import { HTML_LANG, localesForPath, type Locale } from "@/i18n/routing";

const NAMES: Record<string, string> = { en: "English", nl: "Nederlands", zh: "中文" };

/**
 * Links to the current page in each locale it exists in (the locale is the first path
 * segment; zh only for the sections that have Chinese pages).
 */
export function LanguageSwitch({ label, current }: { label: string; current: Locale }) {
  const pathname = usePathname() ?? `/${current}`;
  const rest = pathname.split("/").slice(2).join("/");
  return (
    <nav aria-label={label}>
      <ul className="flex gap-3 text-sm">
        {localesForPath(rest).map((locale) => (
          <li key={locale}>
            {locale === current ? (
              <span aria-current="true" className="font-semibold text-slate-900">
                {NAMES[locale] ?? locale}
              </span>
            ) : (
              <a
                href={`/${locale}${rest ? `/${rest}` : ""}`}
                hrefLang={HTML_LANG[locale]}
                lang={HTML_LANG[locale]}
              >
                {NAMES[locale] ?? locale}
              </a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
