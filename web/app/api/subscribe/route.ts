/**
 * POST /api/subscribe (spec §8): JSON body with email, locale, filters,
 * include_unclassified, instant_sources, consent, consent_text_version and the honeypot
 * field `website`. Answers 202 for every accepted request, whether or not an email is
 * sent (suppressed or already subscribed addresses, honeypot hits): the work runs after
 * the response, so neither the status nor the timing reveals anything about the address.
 *
 * Requiring a JSON content type also blocks cross-site form posts (CSRF): browsers only
 * send JSON cross-origin after a CORS preflight, which this route does not allow.
 */
import { after } from "next/server";
import { clientIp } from "@/lib/rate-limit";
import { knownFilterValues } from "@/lib/subscriptions/catalog";
import {
  CLIENT_IP_HEADER,
  loadFilterCatalog,
  logEvent,
  subscribeLimiter,
  subscriptionDeps,
} from "@/lib/subscriptions/runtime";
import { requestSubscription } from "@/lib/subscriptions/service";
import { parseSubscriptionRequest } from "@/lib/subscriptions/validate";

const NO_STORE = { "cache-control": "no-store" };
const MAX_BODY_BYTES = 16_384;

function reply(status: number, body: object, headers: Record<string, string> = {}) {
  return Response.json(body, { status, headers: { ...NO_STORE, ...headers } });
}

const ACCEPTED = { status: "check_email" };

export async function POST(request: Request) {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return reply(415, { error: "unsupported_media_type" });
  }

  const ip = clientIp(request.headers, CLIENT_IP_HEADER);
  const limit = subscribeLimiter.hit(ip ?? "unknown");
  if (!limit.allowed) {
    logEvent("subscribe_rate_limited");
    return reply(429, { error: "rate_limited" }, { "retry-after": String(limit.retryAfterSeconds) });
  }

  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) return reply(413, { error: "too_large" });
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return reply(400, { error: "invalid", fields: [{ field: "body", code: "invalid" }] });
  }

  // Honeypot: people never see the field, bots fill it. Pretend it worked.
  const honeypot = (body as { website?: unknown } | null)?.website;
  if (typeof honeypot === "string" && honeypot.trim() !== "") {
    logEvent("subscribe_honeypot");
    return reply(202, ACCEPTED);
  }

  const parsed = parseSubscriptionRequest(body, knownFilterValues(await loadFilterCatalog()));
  if (!parsed.ok) return reply(400, { error: "invalid", fields: parsed.errors });

  const deps = subscriptionDeps();
  after(async () => {
    try {
      const outcome = await requestSubscription(deps, parsed.value, ip);
      logEvent("subscription_requested", { outcome, locale: parsed.value.locale });
    } catch (error) {
      logEvent("subscription_request_failed", { error: String(error) });
    }
  });
  return reply(202, ACCEPTED);
}
