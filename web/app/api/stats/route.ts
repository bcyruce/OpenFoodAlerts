import type { NextRequest } from "next/server";
import { isSiteLocale, routing } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { getStats } from "@/lib/stats";
import { parseStatsQuery } from "@/lib/stats-query";

/**
 * GET /api/stats (spec §8): dashboard aggregates per Source. Parameters are the filter part
 * of /api/search (`source[]`, `hazard[]`, `product[]`, `country[]`, `risk[]`, `from`, `to`,
 * `official_only`), parsed by the same code, plus `months` (last N months, default 12;
 * `all` for no lower bound; ignored when `from` or `to` is set) and `locale` (en, nl) for
 * labels. Returns a StatsResponse (`lib/stats.ts`). Runs on every request.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const params = request.nextUrl.searchParams;
  const requested = params.get("locale");
  const locale = requested !== null && isSiteLocale(requested) ? requested : routing.defaultLocale;
  const result = await getStats(getDb(), parseStatsQuery(params), { locale });
  return Response.json(result, { headers: { "X-Robots-Tag": "noindex" } });
}
