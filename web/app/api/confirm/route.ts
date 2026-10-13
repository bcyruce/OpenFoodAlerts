/**
 * POST /api/confirm (spec §8): `{"token": "..."}` from the confirmation link. POST, not
 * GET, so mail scanners that open links cannot confirm on the subscriber's behalf.
 *
 * 200 {"status":"active","manage_path":"/{locale}/alerts/manage/{manage token}"} |
 * 400 {"error":"invalid"} | 410 {"error":"expired"} | 429. The manage path (ticket 29)
 * lets the subscriber change or end the Subscription before the first Digest arrives.
 */
import { clientIp } from "@/lib/rate-limit";
import { manageToken, TOKEN_PATTERN } from "@/lib/subscriptions/crypto";
import {
  CLIENT_IP_HEADER,
  confirmLimiter,
  logEvent,
  subscriptionDeps,
} from "@/lib/subscriptions/runtime";
import { activateSubscription } from "@/lib/subscriptions/service";

const NO_STORE = { "cache-control": "no-store" };

function reply(status: number, body: object, headers: Record<string, string> = {}) {
  return Response.json(body, { status, headers: { ...NO_STORE, ...headers } });
}

export async function POST(request: Request) {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return reply(415, { error: "unsupported_media_type" });
  }
  const ip = clientIp(request.headers, CLIENT_IP_HEADER);
  const limit = confirmLimiter.hit(ip ?? "unknown");
  if (!limit.allowed) {
    return reply(429, { error: "rate_limited" }, { "retry-after": String(limit.retryAfterSeconds) });
  }

  const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
  const token = body?.token;
  if (typeof token !== "string" || !TOKEN_PATTERN.test(token)) {
    return reply(400, { error: "invalid" });
  }

  const deps = subscriptionDeps();
  const result = await activateSubscription(deps, token);
  logEvent("subscription_confirm", { outcome: result.outcome });
  if (result.outcome === "confirmed") {
    const { id, locale } = result.subscription;
    const managePath = `/${locale}/alerts/manage/${manageToken(id, deps.secrets.tokenSecret)}`;
    return reply(200, { status: "active", manage_path: managePath });
  }
  if (result.outcome === "expired") return reply(410, { error: "expired" });
  return reply(400, { error: "invalid" });
}
