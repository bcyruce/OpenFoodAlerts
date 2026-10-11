/**
 * Subscription double opt-in (spec §10, §11.1 #2–#3): request → confirmation email →
 * confirm. Runs as `ofa_web`, which may write `subscriptions` and `email_suppressions` but
 * records confirmation emails only through `record_confirm_delivery()`.
 *
 * The caller never tells the visitor which outcome happened (no address enumeration).
 */
import { randomUUID } from "node:crypto";
import { and, eq, ne, sql } from "drizzle-orm";
import { emailDeliveries, emailSuppressions, subscriptions } from "@/db/generated/schema";
import { renderConfirmEmail } from "@/lib/email/templates";
import type { EmailTransport } from "@/lib/email/transport";
import type { Reader } from "@/lib/notifications";
import { emailHash, ipHash, manageToken, newConfirmToken, tokenHash } from "./crypto";
import type { SubscriptionRequest } from "./validate";

export type SubscriptionSecrets = {
  /** OFA_HASH_PEPPER: keys the email and IP hashes. Never rotate (suppressions depend on it). */
  hashPepper: string;
  /** OFA_TOKEN_SECRET: keys manage tokens. Rotating it invalidates every manage link. */
  tokenSecret: string;
};

export type SubscriptionDeps = {
  db: Reader;
  transport: EmailTransport;
  secrets: SubscriptionSecrets;
  /** Absolute site URL without trailing slash, for links in emails. */
  siteUrl: string;
  now?: () => Date;
};

export const CONFIRM_TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
/** Limits on confirmation emails per address, against using the form to mail-bomb someone. */
export const CONFIRM_RESEND_INTERVAL_MS = 10 * 60 * 1000;
export const CONFIRM_MAX_PER_DAY = 3;

export type RequestOutcome = "sent" | "suppressed" | "already_active" | "throttled";
export type ConfirmOutcome = "confirmed" | "expired" | "invalid";

export function confirmUrl(siteUrl: string, locale: string, token: string): string {
  return `${siteUrl}/${locale}/alerts/confirm#token=${token}`;
}

/** True if the address asked for its data to be deleted: never email it again. */
export async function isSuppressed(db: Reader, email: string, pepper: string): Promise<boolean> {
  const rows = await db
    .select({ hash: emailSuppressions.emailHash })
    .from(emailSuppressions)
    .where(eq(emailSuppressions.emailHash, emailHash(email, pepper)));
  return rows.length > 0;
}

type Prepared = { id: string; token: string } | Exclude<RequestOutcome, "sent">;

async function prepare(
  deps: SubscriptionDeps,
  req: SubscriptionRequest,
  ip: string | null,
  now: Date,
): Promise<Prepared> {
  const { db, secrets } = deps;
  if (await isSuppressed(db, req.email, secrets.hashPepper)) return "suppressed";

  return db.transaction(async (tx) => {
    const [existing] = await tx
      .select({ id: subscriptions.id, status: subscriptions.status })
      .from(subscriptions)
      .where(and(eq(subscriptions.email, req.email), ne(subscriptions.status, "unsubscribed")))
      .for("update");
    if (existing?.status === "active") return "already_active";

    if (existing) {
      const dayAgo = new Date(now.getTime() - 86_400_000).toISOString();
      const [recent] = await tx
        .select({
          last: sql<string | null>`max(${emailDeliveries.sentAt})`,
          today: sql<number>`(count(*) FILTER (WHERE ${emailDeliveries.sentAt} > ${dayAgo}))::int`,
        })
        .from(emailDeliveries)
        .where(
          and(eq(emailDeliveries.subscriptionId, existing.id), eq(emailDeliveries.kind, "confirm")),
        );
      const last = recent?.last ? new Date(recent.last).getTime() : null;
      if (
        (last !== null && now.getTime() - last < CONFIRM_RESEND_INTERVAL_MS) ||
        (recent?.today ?? 0) >= CONFIRM_MAX_PER_DAY
      ) {
        return "throttled";
      }
    }

    const token = newConfirmToken();
    const fields = {
      locale: req.locale,
      filters: req.filters,
      includeUnclassified: req.includeUnclassified,
      instantSources: req.instantSources,
      confirmTokenHash: tokenHash(token),
      confirmExpiresAt: new Date(now.getTime() + CONFIRM_TOKEN_TTL_MS).toISOString(),
      consentAt: now.toISOString(),
      consentTextVersion: req.consentTextVersion,
      consentIpHash: ip ? ipHash(ip, secrets.hashPepper) : null,
    };

    if (existing) {
      await tx.update(subscriptions).set(fields).where(eq(subscriptions.id, existing.id));
      return { id: existing.id, token };
    }
    const id = randomUUID();
    const inserted = await tx
      .insert(subscriptions)
      .values({
        id,
        email: req.email,
        status: "pending",
        manageTokenHash: tokenHash(manageToken(id, secrets.tokenSecret)),
        createdAt: now.toISOString(),
        ...fields,
      })
      // A concurrent request for the same address won the race; it sends the email.
      .onConflictDoNothing()
      .returning({ id: subscriptions.id });
    return inserted.length > 0 ? { id, token } : "throttled";
  });
}

/**
 * Creates or refreshes a pending Subscription and emails the confirmation link. Throws
 * if the email cannot be sent (the Subscription stays pending; a retry sends a new link).
 */
export async function requestSubscription(
  deps: SubscriptionDeps,
  req: SubscriptionRequest,
  ip: string | null,
): Promise<RequestOutcome> {
  const now = (deps.now ?? (() => new Date()))();
  const prepared = await prepare(deps, req, ip, now);
  if (typeof prepared === "string") return prepared;

  const email = renderConfirmEmail({
    locale: req.locale,
    confirmUrl: confirmUrl(deps.siteUrl, req.locale, prepared.token),
    filters: req.filters,
    includeUnclassified: req.includeUnclassified,
    instantSources: req.instantSources,
  });
  const { messageId } = await deps.transport.send({ to: req.email, ...email, tag: "confirm" });
  await deps.db.execute(sql`SELECT record_confirm_delivery(${prepared.id}::uuid, ${messageId})`);
  return "sent";
}

/** Activates the pending Subscription whose confirm token this is (valid 24 hours). */
export async function confirmSubscription(
  deps: Pick<SubscriptionDeps, "db" | "now">,
  token: string,
): Promise<ConfirmOutcome> {
  const now = (deps.now ?? (() => new Date()))().toISOString();
  const hash = tokenHash(token);
  const confirmed = await deps.db
    .update(subscriptions)
    .set({ status: "active", confirmedAt: now, confirmTokenHash: null, confirmExpiresAt: null })
    .where(
      and(
        eq(subscriptions.confirmTokenHash, hash),
        eq(subscriptions.status, "pending"),
        sql`${subscriptions.confirmExpiresAt} > ${now}`,
      ),
    )
    .returning({ id: subscriptions.id });
  if (confirmed.length > 0) return "confirmed";
  const pending = await deps.db
    .select({ id: subscriptions.id })
    .from(subscriptions)
    .where(eq(subscriptions.confirmTokenHash, hash));
  return pending.length > 0 ? "expired" : "invalid";
}
