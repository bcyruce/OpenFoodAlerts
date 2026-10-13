// Manage, unsubscribe and "delete my data" (ticket 29) against TEST_DATABASE_URL, as the
// web role. "Nothing is sent afterwards" is checked through `sendable_subscriptions`,
// the only view of Subscriptions the mailer role has (Digest, Instant email).
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { createMemoryTransport, type EmailMessage } from "@/lib/email/transport";
import { testClient, withRollback, type Tx } from "@/lib/test-db";
import { CONSENT_TEXT_VERSION } from "./consent";
import { emailHash, manageToken } from "./crypto";
import {
  deleteSubscriptionData,
  findSubscription,
  maskEmail,
  unsubscribe,
  updateSubscriptionSettings,
  type ManageDeps,
} from "./manage";
import { confirmSubscription, requestSubscription, type SubscriptionDeps } from "./service";
import type { SubscriptionRequest, SubscriptionSettings } from "./validate";

afterAll(() => testClient.end());

const SECRETS = { hashPepper: "test-pepper", tokenSecret: "test-token-secret" };
const T0 = new Date("2026-10-25T10:00:00Z");
const AS_WEB = { role: "ofa_web" } as const;

const request: SubscriptionRequest = {
  email: "jan@example.nl",
  locale: "nl",
  filters: { sources: ["nvwa", "rasff"], hazard_categories: [21798], product_categories: [], origin_countries: [] },
  includeUnclassified: true,
  instantSources: ["nvwa"],
  consentTextVersion: CONSENT_TEXT_VERSION,
};

function confirmToken(message: EmailMessage): string {
  return message.text.match(/#token=([A-Za-z0-9_-]{43})/)![1];
}

function manageDeps(tx: Tx, now = T0): ManageDeps {
  return { db: tx, secrets: SECRETS, now: () => now };
}

/** An active Subscription, as after the confirmation link; returns its manage token. */
async function activeSubscription(tx: Tx, req: SubscriptionRequest = request): Promise<string> {
  const deps: SubscriptionDeps = {
    db: tx,
    transport: createMemoryTransport(),
    secrets: SECRETS,
    siteUrl: "https://openfoodalerts.nl",
    now: () => T0,
  };
  await requestSubscription(deps, req, null);
  const sent = (deps.transport as ReturnType<typeof createMemoryTransport>).sent;
  await confirmSubscription(deps, confirmToken(sent[0]));
  const [row] = await tx.execute<{ id: string }>(
    sql`SELECT id FROM subscriptions WHERE email = ${req.email} AND status = 'active'`,
  );
  return manageToken(row.id, SECRETS.tokenSecret);
}

/** A rolled-back transaction as ofa_web, without rows other test suites left behind. */
function fresh(fn: (tx: Tx) => Promise<void>) {
  return withRollback(async (tx) => {
    await tx.execute(sql`DELETE FROM subscriptions`);
    await tx.execute(sql`DELETE FROM email_suppressions`);
    await fn(tx);
  }, AS_WEB);
}

/** Who the Digest / Instant email jobs would email right now, read as ofa_mailer. */
async function sendableEmails(tx: Tx): Promise<string[]> {
  await tx.execute(sql`SET LOCAL ROLE ofa_mailer`);
  const rows = await tx.execute<{ email: string }>(sql`SELECT email FROM sendable_subscriptions ORDER BY email`);
  await tx.execute(sql`SET LOCAL ROLE ofa_web`);
  return rows.map((r) => r.email);
}

describe("findSubscription", () => {
  it("finds a Subscription by its manage token and shows only a masked address", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      expect(await findSubscription(tx, token)).toEqual({
        maskedEmail: "j***@example.nl",
        status: "active",
        locale: "nl",
        filters: request.filters,
        includeUnclassified: true,
        instantSources: ["nvwa"],
        unsubscribedAt: null,
      });
      expect(await findSubscription(tx, manageToken("00000000-0000-4000-8000-000000000000", SECRETS.tokenSecret))).toBeNull();
    }));
});

describe("updateSubscriptionSettings", () => {
  const changed: SubscriptionSettings = {
    locale: "zh",
    filters: { sources: ["nvwa"], hazard_categories: [], product_categories: [], origin_countries: ["CN"] },
    includeUnclassified: false,
    instantSources: [],
  };

  it("replaces filters, language and Instant email settings", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      expect(await updateSubscriptionSettings(manageDeps(tx), token, changed)).toBe("updated");
      expect(await findSubscription(tx, token)).toMatchObject({
        status: "active",
        locale: "zh",
        filters: changed.filters,
        includeUnclassified: false,
        instantSources: [],
      });
      expect(await sendableEmails(tx)).toEqual(["jan@example.nl"]);
    }));

  it("does not change an unsubscribed Subscription or an unknown token", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      await unsubscribe(manageDeps(tx), token);
      expect(await updateSubscriptionSettings(manageDeps(tx), token, changed)).toBe("unsubscribed");
      expect((await findSubscription(tx, token))?.locale).toBe("nl");
      expect(await updateSubscriptionSettings(manageDeps(tx), "x".repeat(43), changed)).toBe("invalid");
    }));
});

describe("unsubscribe", () => {
  it("stops all sending at once and records when", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      await activeSubscription(tx, { ...request, email: "piet@example.nl" });
      expect(await sendableEmails(tx)).toEqual(["jan@example.nl", "piet@example.nl"]);

      const later = new Date(T0.getTime() + 3_600_000);
      expect(await unsubscribe(manageDeps(tx, later), token)).toBe("unsubscribed");
      expect(await sendableEmails(tx)).toEqual(["piet@example.nl"]);
      const found = await findSubscription(tx, token);
      expect(found?.status).toBe("unsubscribed");
      expect(new Date(found!.unsubscribedAt!).getTime()).toBe(later.getTime());
    }));

  it("is idempotent, so a repeated one-click POST keeps the first date", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      await unsubscribe(manageDeps(tx), token);
      const again = new Date(T0.getTime() + 86_400_000);
      expect(await unsubscribe(manageDeps(tx, again), token)).toBe("already_unsubscribed");
      expect(new Date((await findSubscription(tx, token))!.unsubscribedAt!).getTime()).toBe(T0.getTime());
      expect(await unsubscribe(manageDeps(tx), "x".repeat(43))).toBe("invalid");
    }));

  it("also ends a pending Subscription and voids its confirmation link", () =>
    fresh(async (tx) => {
      const transport = createMemoryTransport();
      const deps = { db: tx, transport, secrets: SECRETS, siteUrl: "https://x.test", now: () => T0 };
      await requestSubscription(deps, request, null);
      const [row] = await tx.execute<{ id: string }>(sql`SELECT id FROM subscriptions`);
      expect(await unsubscribe(manageDeps(tx), manageToken(row.id, SECRETS.tokenSecret))).toBe("unsubscribed");
      expect(await confirmSubscription(deps, confirmToken(transport.sent[0]))).toBe("invalid");
      expect(await sendableEmails(tx)).toEqual([]);
    }));
});

describe("deleteSubscriptionData", () => {
  it("deletes every Subscription of the address with its deliveries and keeps only the hash", () =>
    fresh(async (tx) => {
      const old = await activeSubscription(tx);
      await unsubscribe(manageDeps(tx), old);
      const token = await activeSubscription(tx);
      await activeSubscription(tx, { ...request, email: "piet@example.nl" });

      const deliveriesTo = async () =>
        (
          await tx.execute<{ email: string }>(sql`
            SELECT s.email FROM email_deliveries d JOIN subscriptions s ON s.id = d.subscription_id ORDER BY 1`)
        ).map((r) => r.email);
      // One confirmation email each.
      expect(await deliveriesTo()).toEqual(["jan@example.nl", "jan@example.nl", "piet@example.nl"]);

      expect(await deleteSubscriptionData(manageDeps(tx), token)).toBe("deleted");

      const left = await tx.execute<{ email: string }>(sql`SELECT email FROM subscriptions`);
      expect(left.map((r) => r.email)).toEqual(["piet@example.nl"]);
      const [{ n }] = await tx.execute<{ n: number }>(sql`SELECT count(*)::int AS n FROM email_deliveries`);
      expect(n).toBe(1);
      expect(await deliveriesTo()).toEqual(["piet@example.nl"]);
      const suppressions = await tx.execute<{ email_hash: string }>(sql`SELECT email_hash FROM email_suppressions`);
      expect(suppressions.map((r) => r.email_hash)).toEqual([emailHash("jan@example.nl", SECRETS.hashPepper)]);
      expect(await sendableEmails(tx)).toEqual(["piet@example.nl"]);
      expect(await findSubscription(tx, token)).toBeNull();
      expect(await findSubscription(tx, old)).toBeNull();
    }));

  it("blocks the address from subscribing again, and an unknown token deletes nothing", () =>
    fresh(async (tx) => {
      const token = await activeSubscription(tx);
      expect(await deleteSubscriptionData(manageDeps(tx), "x".repeat(43))).toBe("invalid");
      expect(await deleteSubscriptionData(manageDeps(tx), token)).toBe("deleted");
      expect(await deleteSubscriptionData(manageDeps(tx), token)).toBe("invalid");
      const transport = createMemoryTransport();
      const deps = { db: tx, transport, secrets: SECRETS, siteUrl: "https://x.test", now: () => T0 };
      expect(await requestSubscription(deps, request, null)).toBe("suppressed");
      expect(transport.sent).toEqual([]);
    }));
});

describe("maskEmail", () => {
  it("keeps the first character and the domain", () => {
    expect(maskEmail("jan@example.nl")).toBe("j***@example.nl");
    expect(maskEmail("a@b.co")).toBe("a***@b.co");
  });
});
