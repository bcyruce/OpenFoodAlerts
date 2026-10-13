/**
 * /api/manage (spec §8): read and change a Subscription with its manage token.
 *
 * - GET ?token=…: 200 {"subscription": ManagedSubscription} | 400 invalid | 404 not_found.
 * - POST JSON {token, locale, filters, include_unclassified, instant_sources}: same rules
 *   as /api/subscribe (zh ⇒ NVWA only, instant_sources ⊆ sources). 200 {"status":
 *   "updated", "subscription": …} | 400 invalid (+ fields) | 404 | 409 unsubscribed | 415.
 *
 * The address and consent cannot be changed here: a new address needs its own
 * confirmation, so subscribers unsubscribe and subscribe again.
 */
import type { NextRequest } from "next/server";
import { isJson, jsonBody, rateLimited, reply } from "@/lib/subscriptions/http";
import { tokenFromLink } from "@/lib/subscriptions/links";
import { findSubscription, updateSubscriptionSettings } from "@/lib/subscriptions/manage";
import { knownFilterValues } from "@/lib/subscriptions/catalog";
import { loadFilterCatalog, logEvent, manageDeps, manageLimiter } from "@/lib/subscriptions/runtime";
import { parseSubscriptionSettings } from "@/lib/subscriptions/validate";

export async function GET(request: NextRequest) {
  const limited = rateLimited(request, manageLimiter);
  if (limited) return limited;
  const token = tokenFromLink(request.nextUrl.searchParams.get("token"));
  if (!token) return reply(400, { error: "invalid" });
  const subscription = await findSubscription(manageDeps().db, token);
  if (!subscription) return reply(404, { error: "not_found" });
  return reply(200, { subscription });
}

export async function POST(request: Request) {
  if (!isJson(request)) return reply(415, { error: "unsupported_media_type" });
  const limited = rateLimited(request, manageLimiter);
  if (limited) return limited;
  const body = await jsonBody(request);
  const token = tokenFromLink(body?.token);
  if (!token) return reply(400, { error: "invalid", fields: [{ field: "token", code: "invalid" }] });

  const parsed = parseSubscriptionSettings(body, knownFilterValues(await loadFilterCatalog()));
  if (!parsed.ok) return reply(400, { error: "invalid", fields: parsed.errors });

  const deps = manageDeps();
  const outcome = await updateSubscriptionSettings(deps, token, parsed.value);
  logEvent("subscription_updated", { outcome });
  if (outcome === "invalid") return reply(404, { error: "not_found" });
  if (outcome === "unsubscribed") return reply(409, { error: "unsubscribed" });
  return reply(200, { status: "updated", subscription: await findSubscription(deps.db, token) });
}
