/**
 * Response helpers for the token-authorised routes (/api/manage, /api/unsubscribe,
 * /api/delete): never cached, never indexed, and no Referer carrying the token onwards.
 */
import { clientIp, type RateLimiter } from "@/lib/rate-limit";
import { CLIENT_IP_HEADER } from "./runtime";

export const PRIVATE_HEADERS = {
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-robots-tag": "noindex",
} as const;

export function reply(status: number, body: object, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...PRIVATE_HEADERS, ...headers } });
}

export function isJson(request: Request): boolean {
  return request.headers.get("content-type")?.toLowerCase().startsWith("application/json") ?? false;
}

/** JSON body as an object, or null when it is missing or malformed. */
export async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  const body: unknown = await request.json().catch(() => null);
  return typeof body === "object" && body !== null && !Array.isArray(body)
    ? (body as Record<string, unknown>)
    : null;
}

/** A 429 response when this client is over the limit, otherwise null. */
export function rateLimited(request: Request, limiter: RateLimiter): Response | null {
  const limit = limiter.hit(clientIp(request.headers, CLIENT_IP_HEADER) ?? "unknown");
  if (limit.allowed) return null;
  return reply(429, { error: "rate_limited" }, { "retry-after": String(limit.retryAfterSeconds) });
}
