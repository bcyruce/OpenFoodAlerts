/**
 * In-memory rate limiting by client IP (spec §11.2). v1 runs one Next.js process, so a
 * per-process sliding window is enough; with several instances, move this to Postgres
 * or Redis. Limits reset when the server restarts.
 */
import { isIP } from "node:net";

export type RateLimiter = {
  hit(key: string): { allowed: boolean; retryAfterSeconds: number };
  size(): number;
};

export function createRateLimiter(options: {
  limit: number;
  windowMs: number;
  now?: () => number;
  maxKeys?: number;
}): RateLimiter {
  const { limit, windowMs } = options;
  const now = options.now ?? Date.now;
  const maxKeys = options.maxKeys ?? 10_000;
  const hits = new Map<string, number[]>();

  function prune(t: number) {
    for (const [key, times] of hits) {
      if (times[times.length - 1] <= t - windowMs) hits.delete(key);
    }
    // Still too many active keys (e.g. a flood from many addresses): drop the oldest.
    while (hits.size >= maxKeys) hits.delete(hits.keys().next().value!);
  }

  return {
    hit(key) {
      const t = now();
      const recent = (hits.get(key) ?? []).filter((time) => time > t - windowMs);
      if (recent.length >= limit) {
        hits.set(key, recent);
        return { allowed: false, retryAfterSeconds: Math.ceil((recent[0] + windowMs - t) / 1000) };
      }
      if (!hits.has(key) && hits.size >= maxKeys) prune(t);
      recent.push(t);
      hits.delete(key);
      hits.set(key, recent);
      return { allowed: true, retryAfterSeconds: 0 };
    },
    size: () => {
      prune(now());
      return hits.size;
    },
  };
}

/** Parses "COUNT/SECONDS" (e.g. SUBSCRIBE_RATE_LIMIT=5/600). */
export function parseRateLimit(
  value: string | undefined,
  fallback: { limit: number; windowMs: number },
): { limit: number; windowMs: number } {
  const match = value?.match(/^(\d+)\/(\d+)$/);
  if (!match) return fallback;
  return { limit: Number(match[1]), windowMs: Number(match[2]) * 1000 };
}

/**
 * The client address from `header` (CLIENT_IP_HEADER, default x-forwarded-for). For a
 * list, the last entry is the one added by our own reverse proxy; earlier entries are
 * whatever the client sent. Without a proxy, Next.js sets x-forwarded-for itself only
 * when the client did not send one, so production must run behind a proxy that sets it.
 */
export function clientIp(headers: Headers, header: string): string | null {
  const value = headers.get(header);
  if (!value) return null;
  const last = value.split(",").pop()!.trim();
  return isIP(last) ? last : null;
}
