/**
 * The manage link (spec §8, §9, §11.1 #5): view and change a Subscription, unsubscribe,
 * or delete my data. Every operation is authorised by the manage token alone (no
 * account, no cookies); the Subscription is found by the token's SHA-256, the only form
 * in which the database knows it. Runs as `ofa_web`.
 *
 * Sending stops through the `sendable_subscriptions` view, the mailer's only view of
 * Subscriptions: it shows active rows whose address is not suppressed.
 */
import { and, eq, ne } from "drizzle-orm";
import { emailSuppressions, subscriptions } from "@/db/generated/schema";
import type { Reader } from "@/lib/notifications";
import { emailHash, tokenHash } from "./crypto";
import type { SubscriptionSecrets } from "./service";
import type { SourceCode, SubscriptionFilters, SubscriptionLocale, SubscriptionSettings } from "./validate";

export type ManageDeps = {
  db: Reader;
  secrets: Pick<SubscriptionSecrets, "hashPepper">;
  now?: () => Date;
};

export type SubscriptionStatus = "pending" | "active" | "unsubscribed";

/** What the manage page shows. The address is masked: the link may have been forwarded. */
export type ManagedSubscription = SubscriptionSettings & {
  maskedEmail: string;
  status: SubscriptionStatus;
  /** ISO timestamp. */
  unsubscribedAt: string | null;
};

export type UpdateOutcome = "updated" | "unsubscribed" | "invalid";
export type UnsubscribeOutcome = "unsubscribed" | "already_unsubscribed" | "invalid";
export type DeleteOutcome = "deleted" | "invalid";

/** "jan@example.nl" → "j***@example.nl" (the length of the local part is not shown). */
export function maskEmail(email: string): string {
  const at = email.lastIndexOf("@");
  return `${email.slice(0, 1)}***${email.slice(at)}`;
}

const byToken = (token: string) => eq(subscriptions.manageTokenHash, tokenHash(token));
const nowIso = (deps: ManageDeps) => (deps.now ?? (() => new Date()))().toISOString();

export async function findSubscription(db: Reader, token: string): Promise<ManagedSubscription | null> {
  const [row] = await db
    .select({
      email: subscriptions.email,
      status: subscriptions.status,
      locale: subscriptions.locale,
      filters: subscriptions.filters,
      includeUnclassified: subscriptions.includeUnclassified,
      instantSources: subscriptions.instantSources,
      unsubscribedAt: subscriptions.unsubscribedAt,
    })
    .from(subscriptions)
    .where(byToken(token));
  if (!row) return null;
  return {
    maskedEmail: maskEmail(row.email),
    status: row.status as SubscriptionStatus,
    locale: row.locale as SubscriptionLocale,
    filters: row.filters as SubscriptionFilters,
    includeUnclassified: row.includeUnclassified,
    instantSources: row.instantSources as SourceCode[],
    unsubscribedAt: row.unsubscribedAt ? new Date(row.unsubscribedAt).toISOString() : null,
  };
}

async function exists(db: Reader, token: string): Promise<boolean> {
  const rows = await db.select({ id: subscriptions.id }).from(subscriptions).where(byToken(token));
  return rows.length > 0;
}

/** Changes filters, language and Instant email settings; not after unsubscribing. */
export async function updateSubscriptionSettings(
  deps: ManageDeps,
  token: string,
  settings: SubscriptionSettings,
): Promise<UpdateOutcome> {
  const updated = await deps.db
    .update(subscriptions)
    .set({
      locale: settings.locale,
      filters: settings.filters,
      includeUnclassified: settings.includeUnclassified,
      instantSources: settings.instantSources,
    })
    .where(and(byToken(token), ne(subscriptions.status, "unsubscribed")))
    .returning({ id: subscriptions.id });
  if (updated.length > 0) return "updated";
  return (await exists(deps.db, token)) ? "unsubscribed" : "invalid";
}

/**
 * Stops all email at once (also for a pending Subscription, whose confirmation link stops
 * working). Idempotent: repeating it keeps the first `unsubscribed_at`, from which the
 * Subscription is deleted after 30 days (`cleanup-subscriptions`).
 */
export async function unsubscribe(deps: ManageDeps, token: string): Promise<UnsubscribeOutcome> {
  const done = await deps.db
    .update(subscriptions)
    .set({ status: "unsubscribed", unsubscribedAt: nowIso(deps), confirmTokenHash: null, confirmExpiresAt: null })
    .where(and(byToken(token), ne(subscriptions.status, "unsubscribed")))
    .returning({ id: subscriptions.id });
  if (done.length > 0) return "unsubscribed";
  return (await exists(deps.db, token)) ? "already_unsubscribed" : "invalid";
}

/**
 * "Delete my data": deletes every Subscription of this address (an earlier, unsubscribed
 * one too) with its deliveries (ON DELETE CASCADE), and puts the address's HMAC on the
 * do-not-send list, which also blocks subscribing again with it.
 */
export async function deleteSubscriptionData(deps: ManageDeps, token: string): Promise<DeleteOutcome> {
  return deps.db.transaction(async (tx) => {
    const [row] = await tx
      .select({ email: subscriptions.email })
      .from(subscriptions)
      .where(byToken(token))
      .for("update");
    if (!row) return "invalid";
    await tx
      .insert(emailSuppressions)
      .values({ emailHash: emailHash(row.email, deps.secrets.hashPepper), createdAt: nowIso(deps) })
      .onConflictDoNothing();
    await tx.delete(subscriptions).where(eq(subscriptions.email, row.email));
    return "deleted";
  });
}
