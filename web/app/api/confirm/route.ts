/**
 * POST /api/confirm (spec §8): `{"token": "..."}` from the confirmation link. POST, not
 * GET, so mail scanners that open links cannot confirm on the subscriber's behalf.
 *
 * 200 {"status":"active"} | 400 {"error":"invalid"} | 410 {"error":"expired"} | 429.
 */
import { clientIp } from "@/lib/rate-limit";
import { TOKEN_PATTERN } from "@/lib/subscriptions/crypto";
import {
  CLIENT_IP_HEADER,
  confirmLimiter,
  logEvent,
  subscriptionDeps,
} from "@/lib/subscriptions/runtime";
import { confirmSubscription } from "@/lib/subscriptions/service";

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

  const outcome = await confirmSubscription(subscriptionDeps(), token);
  logEvent("subscription_confirm", { outcome });
  if (outcome === "confirmed") return reply(200, { status: "active" });
  if (outcome === "expired") return reply(410, { error: "expired" });
  return reply(400, { error: "invalid" });
}
