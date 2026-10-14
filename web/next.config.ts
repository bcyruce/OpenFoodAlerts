import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Pages and routes whose URL carries a manage token (ticket 29): keep it out of Referer
// headers, caches and search engines.
const TOKEN_HEADERS = [
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cache-Control", value: "no-store" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  headers() {
    return [
      { source: "/:locale/alerts/manage/:token*", headers: TOKEN_HEADERS },
      { source: "/api/(manage|unsubscribe|delete)", headers: TOKEN_HEADERS },
    ];
  },
  // /data exists only in English (spec §9). Temporary, in case a translation follows.
  redirects() {
    return [
      { source: "/:locale(nl|zh)/data", destination: "/en/data", permanent: false },
    ];
  },
  partialPrefetching: true,
  experimental: {
    // app/global-not-found.tsx serves URLs outside /en and /nl.
    globalNotFound: true,
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default createNextIntlPlugin("./i18n/request.ts")(nextConfig);
