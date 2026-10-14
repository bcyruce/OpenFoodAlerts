import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Crawlers may fetch every page; search, subscription and manage pages say `noindex` in
// their own metadata (and must stay crawlable for that to be seen). The JSON API is not
// for crawlers.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
