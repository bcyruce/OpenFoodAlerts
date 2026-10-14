"use client";

import { usePathname } from "next/navigation";
import type { SyntheticEvent } from "react";
import { HTML_LANG, localesForPath, type Locale } from "@/i18n/routing";

const NAMES: Record<string, string> = { en: "English", nl: "Nederlands", zh: "中文" };

/**
 * The current query string (search and dashboard filters), added to a link just before it
 * is followed. Read at that moment because the dashboard updates the address bar with
 * `history.replaceState`, which React does not see. The fragment is never carried over.
 */
function withCurrentQuery(event: SyntheticEvent<HTMLAnchorElement>) {
  const link = event.currentTarget;
  const base = link.getAttribute("data-path") ?? link.pathname;
  link.href = `${base}${window.location.search}`;
}

/**
 * Links to the current page in each locale it exists in (the locale is the first path
 * segment; zh only for the sections that have Chinese pages). Filters in the query string
 * are kept.
 */
export function LanguageSwitch({ label, current }: { label: string; current: Locale }) {
  const pathname = usePathname() ?? `/${current}`;
  const rest = pathname.split("/").slice(2).join("/");
  return (
    <nav aria-label={label}>
      <ul className="flex gap-3 text-sm">
        {localesForPath(rest).map((locale) => {
          const path = `/${locale}${rest ? `/${rest}` : ""}`;
          return (
            <li key={locale}>
              {locale === current ? (
                <span aria-current="true" className="font-semibold text-slate-900">
                  {NAMES[locale] ?? locale}
                </span>
              ) : (
                <a
                  href={path}
                  data-path={path}
                  hrefLang={HTML_LANG[locale]}
                  lang={HTML_LANG[locale]}
                  onPointerDown={withCurrentQuery}
                  onFocus={withCurrentQuery}
                  onClick={withCurrentQuery}
                  onContextMenu={withCurrentQuery}
                >
                  {NAMES[locale] ?? locale}
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
