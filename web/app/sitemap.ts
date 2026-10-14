import type { MetadataRoute } from "next";
import { cacheLife } from "next/cache";
import { getDb } from "@/lib/db";
import { listSitemapNotifications } from "@/lib/notifications";
import { SITE_URL } from "@/lib/site";
import { buildSitemap, SITEMAP_NOTIFICATIONS } from "@/lib/sitemap";

// `use cache` cannot sit in the route body itself; regenerated at most once an hour.
async function entries(): Promise<MetadataRoute.Sitemap> {
  "use cache";
  cacheLife("hours");
  return buildSitemap(SITE_URL, await listSitemapNotifications(getDb(), SITEMAP_NOTIFICATIONS));
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  return entries();
}
