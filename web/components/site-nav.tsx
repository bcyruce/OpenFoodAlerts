"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isCurrentNav, type NavItem } from "@/lib/site-links";

/** The header navigation (Home, Dashboard, Search, Evaluation, Subscribe); marks the current section. */
export function SiteNav({
  label,
  items,
}: {
  label: string;
  items: (NavItem & { label: string })[];
}) {
  const pathname = usePathname() ?? "";
  return (
    <nav aria-label={label}>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {items.map((item) => {
          const current = isCurrentNav(item, pathname);
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                hrefLang={item.hrefLang}
                aria-current={current ? "page" : undefined}
                className={current ? "font-semibold text-slate-900 decoration-2" : undefined}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
