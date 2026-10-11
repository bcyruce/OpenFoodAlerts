/**
 * Server-side wiring of the subscription flow from environment variables:
 *
 * - OFA_HASH_PEPPER, OFA_TOKEN_SECRET: required in production (see SubscriptionSecrets).
 * - EMAIL_TRANSPORT and friends: see lib/email/transport.ts.
 * - CLIENT_IP_HEADER: header with the client address (default x-forwarded-for).
 * - SUBSCRIBE_RATE_LIMIT / CONFIRM_RATE_LIMIT: "COUNT/SECONDS" per IP (default 5/600, 20/600).
 * - SITE_URL: base of the links in emails.
 */
import { cacheLife } from "next/cache";
import { transportFromEnv } from "@/lib/email/transport";
import { getDb } from "@/lib/db";
import { createRateLimiter, parseRateLimit } from "@/lib/rate-limit";
import { SITE_URL } from "@/lib/site";
import { getFilterCatalog, type FilterCatalog } from "./catalog";
import type { SubscriptionDeps, SubscriptionSecrets } from "./service";

const DEV_SECRET = "development-only-not-secret";

function secret(name: string): string {
  const value = process.env[name];
  if (value) return value;
  if (process.env.NODE_ENV === "production") throw new Error(`${name} is not set`);
  return DEV_SECRET;
}

export function secretsFromEnv(): SubscriptionSecrets {
  return { hashPepper: secret("OFA_HASH_PEPPER"), tokenSecret: secret("OFA_TOKEN_SECRET") };
}

let deps: SubscriptionDeps | undefined;

/** Throws on missing configuration, so callers can answer 500 before accepting work. */
export function subscriptionDeps(): SubscriptionDeps {
  deps ??= {
    db: getDb(),
    transport: transportFromEnv(),
    secrets: secretsFromEnv(),
    siteUrl: SITE_URL,
  };
  return deps;
}

export const CLIENT_IP_HEADER = (process.env.CLIENT_IP_HEADER ?? "x-forwarded-for").toLowerCase();

export const subscribeLimiter = createRateLimiter(
  parseRateLimit(process.env.SUBSCRIBE_RATE_LIMIT, { limit: 5, windowMs: 600_000 }),
);
export const confirmLimiter = createRateLimiter(
  parseRateLimit(process.env.CONFIRM_RATE_LIMIT, { limit: 20, windowMs: 600_000 }),
);

/** Seed data changes rarely; cached for the form and for validating /api/subscribe. */
export async function loadFilterCatalog(): Promise<FilterCatalog> {
  "use cache";
  cacheLife("hours");
  return getFilterCatalog(getDb());
}

/** One JSON line per event, without addresses, IPs or tokens. */
export function logEvent(event: string, fields: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ event, ...fields }));
}
