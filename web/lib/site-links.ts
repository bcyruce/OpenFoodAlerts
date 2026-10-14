/**
 * Header navigation and footer links per locale. Pure and client-safe. Keys are message
 * keys in the `Nav` and `Footer` namespaces.
 */
import { isSiteLocale } from "@/i18n/routing";

export type NavItem = { key: "home" | "dashboard" | "search" | "subscribe"; href: string };

/** The main sections; zh has only the subscription flow until the Chinese module (ticket 32). */
export function navItems(locale: string): NavItem[] {
  if (!isSiteLocale(locale)) return [{ key: "subscribe", href: `/${locale}/alerts` }];
  return [
    { key: "home", href: `/${locale}` },
    { key: "dashboard", href: `/${locale}/dashboard` },
    { key: "search", href: `/${locale}/search` },
    { key: "subscribe", href: `/${locale}/alerts` },
  ];
}

/** Home is current only on the home page; a section also on its subpages. */
export function isCurrentNav(item: NavItem, pathname: string): boolean {
  const path = pathname.replace(/\/+$/, "");
  if (item.key === "home") return path === item.href;
  return path === item.href || path.startsWith(`${item.href}/`);
}

export type FooterLink = {
  key: "data" | "about" | "privacy" | "disclaimerLink" | "colofon";
  href: string;
  /** Set when the target is in another language than the page. */
  hrefLang?: string;
};

/** The data and legal pages (ticket 27). /data is English only (spec §9). */
export function footerLinks(locale: string): FooterLink[] {
  return [
    locale === "en" ? { key: "data", href: "/en/data" } : { key: "data", href: "/en/data", hrefLang: "en" },
    { key: "about", href: `/${locale}/about` },
    { key: "privacy", href: `/${locale}/privacy` },
    { key: "disclaimerLink", href: `/${locale}/disclaimer` },
    { key: "colofon", href: `/${locale}/colofon` },
  ];
}
