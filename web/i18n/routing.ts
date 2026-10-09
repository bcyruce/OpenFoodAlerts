import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  // zh is added with the Chinese pages (tickets 32, 33).
  locales: ["en", "nl"],
  defaultLocale: "en",
  localePrefix: "always",
  // No cookies on this site (spec §11.1 #8); hreflang links come from page metadata.
  localeCookie: false,
  alternateLinks: false,
});

export type Locale = (typeof routing.locales)[number];
