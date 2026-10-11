import type { NextRequest } from "next/server";
import { isSiteLocale, routing } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { parseSearchQuery } from "@/lib/filters";
import { searchNotifications } from "@/lib/search";

/**
 * GET /api/search (spec §8): `q`, `source[]`, `hazard[]`, `product[]`, `country[]`, `risk[]`,
 * `from`, `to`, `official_only`, `page`; also `locale` (en, nl) for labels and detail-page
 * paths. Array parameters may be written with or without `[]`. Returns a SearchResponse
 * (`lib/search.ts`). Runs on every request; nothing is cached.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const params = request.nextUrl.searchParams;
  const requested = params.get("locale");
  const locale = requested !== null && isSiteLocale(requested) ? requested : routing.defaultLocale;
  const result = await searchNotifications(getDb(), parseSearchQuery(params), { locale });
  return Response.json(result, { headers: { "X-Robots-Tag": "noindex" } });
}
