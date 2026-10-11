// The subscription service against TEST_DATABASE_URL, running as the web role so the
// migration's grants are exercised too.
import { sql } from "drizzle-orm";
import { afterAll, describe, expect, it } from "vitest";
import { createMemoryTransport, type EmailMessage } from "@/lib/email/transport";
import { pgErrorCode, testClient, withRollback, type Tx } from "@/lib/test-db";
import { CONSENT_TEXT_VERSION } from "./consent";
import { emailHash, ipHash, manageToken, tokenHash } from "./crypto";
import { confirmSubscription, requestSubscription, type SubscriptionDeps } from "./service";
import type { SubscriptionRequest } from "./validate";

afterAll(() => testClient.end());

const SECRETS = { hashPepper: "test-pepper", tokenSecret: "test-token-secret" };
const T0 = new Date();
const minutes = (n: number) => new Date(T0.getTime() + n * 60_000);

function deps(tx: Tx, now = T0) {
  const transport = createMemoryTransport();
  const d: SubscriptionDeps = {
    db: tx,
    transport,
    secrets: SECRETS,
    siteUrl: "https://openfoodalerts.nl",
    now: () => now,
  };
  return { ...d, transport };
}

const request: SubscriptionRequest = {
  email: "jan@example.nl",
  locale: "nl",
  filters: { sources: ["nvwa", "rasff"], hazard_categories: [21798], product_categories: [], origin_countries: [] },
  includeUnclassified: true,
  instantSources: ["nvwa"],
  consentTextVersion: CONSENT_TEXT_VERSION,
};

function tokenFrom(message: EmailMessage): string {
  const match = message.text.match(/\/(?:en|nl|zh)\/alerts\/confirm#token=([A-Za-z0-9_-]{43})/);
  if (!match) throw new Error(`no confirm link in:\n${message.text}`);
  return match[1];
}

async function subscriptionRow(tx: Tx, email: string) {
  const rows = await tx.execute<Record<string, unknown>>(
    sql`SELECT * FROM subscriptions WHERE email = ${email} ORDER BY created_at DESC`,
  );
  return rows[0];
}

const AS_WEB = { role: "ofa_web" } as const;

describe("requestSubscription and confirmSubscription", () => {
  it("emails a confirmation link that activates the Subscription once", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      expect(await requestSubscription(d, request, "203.0.113.7")).toBe("sent");
      expect(d.transport.sent).toHaveLength(1);
      const [email] = d.transport.sent;
      expect(email.to).toBe("jan@example.nl");
      expect(email.subject).toBe("Bevestig uw abonnement op OpenFoodAlerts");
      expect(email.tag).toBe("confirm");

      const token = tokenFrom(email);
      expect(await confirmSubscription(d, token)).toBe("confirmed");
      expect((await subscriptionRow(tx, "jan@example.nl")).status).toBe("active");
      expect(await confirmSubscription(d, token)).toBe("invalid");
    }, AS_WEB));

  it("stores consent evidence and only hashes of tokens and the IP address", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, "203.0.113.7");
      const token = tokenFrom(d.transport.sent[0]);
      const row = await subscriptionRow(tx, "jan@example.nl");
      expect(row).toMatchObject({
        status: "pending",
        locale: "nl",
        filters: request.filters,
        include_unclassified: true,
        instant_sources: ["nvwa"],
        consent_text_version: CONSENT_TEXT_VERSION,
        consent_ip_hash: ipHash("203.0.113.7", SECRETS.hashPepper),
        confirm_token_hash: tokenHash(token),
        manage_token_hash: tokenHash(manageToken(row.id as string, SECRETS.tokenSecret)),
      });
      expect(new Date(row.consent_at as string).getTime()).toBe(T0.getTime());
      expect(new Date(row.confirm_expires_at as string).getTime()).toBe(minutes(24 * 60).getTime());
      const stored = JSON.stringify(row);
      expect(stored).not.toContain(token);
      expect(stored).not.toContain("203.0.113.7");
    }, AS_WEB));

  it("records the confirmation email in email_deliveries", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      const rows = await tx.execute(sql`
        SELECT d.kind, d.provider_message_id, d.notification_ids
        FROM email_deliveries d JOIN subscriptions s ON s.id = d.subscription_id
        WHERE s.email = 'jan@example.nl'`);
      expect(rows).toEqual([{ kind: "confirm", provider_message_id: "memory-1", notification_ids: [] }]);
    }, AS_WEB));

  it("rejects a confirmation link older than 24 hours", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      const token = tokenFrom(d.transport.sent[0]);
      expect(await confirmSubscription(deps(tx, minutes(24 * 60 + 1)), token)).toBe("expired");
      expect((await subscriptionRow(tx, "jan@example.nl")).status).toBe("pending");
      expect(await confirmSubscription(d, "x".repeat(43))).toBe("invalid");
    }, AS_WEB));

  it("sends nothing to a suppressed address", () =>
    withRollback(async (tx) => {
      await tx.execute(sql`INSERT INTO email_suppressions (email_hash)
        VALUES (${emailHash("jan@example.nl", SECRETS.hashPepper)})`);
      const d = deps(tx);
      expect(await requestSubscription(d, request, null)).toBe("suppressed");
      expect(d.transport.sent).toEqual([]);
      expect(await subscriptionRow(tx, "jan@example.nl")).toBeUndefined();
    }, AS_WEB));

  it("leaves an active Subscription alone and sends nothing", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      await confirmSubscription(d, tokenFrom(d.transport.sent[0]));
      const later = deps(tx, minutes(60));
      const changed = { ...request, filters: { ...request.filters, sources: [] }, instantSources: [] };
      expect(await requestSubscription(later, changed, null)).toBe("already_active");
      expect(later.transport.sent).toEqual([]);
      expect((await subscriptionRow(tx, "jan@example.nl")).filters).toEqual(request.filters);
    }, AS_WEB));

  it("replaces the token of a pending Subscription, at most once per 10 minutes", () =>
    withRollback(async (tx) => {
      const first = deps(tx);
      await requestSubscription(first, request, null);
      const oldToken = tokenFrom(first.transport.sent[0]);

      const soon = deps(tx, minutes(5));
      expect(await requestSubscription(soon, request, null)).toBe("throttled");
      expect(soon.transport.sent).toEqual([]);

      const later = deps(tx, minutes(11));
      const zh = { ...request, locale: "zh" as const, filters: { ...request.filters, sources: ["nvwa" as const] } };
      expect(await requestSubscription(later, zh, null)).toBe("sent");
      const newToken = tokenFrom(later.transport.sent[0]);
      expect(later.transport.sent[0].subject).toBe("请确认您的 OpenFoodAlerts 订阅");
      expect(await confirmSubscription(later, oldToken)).toBe("invalid");
      expect(await confirmSubscription(later, newToken)).toBe("confirmed");
      expect((await subscriptionRow(tx, "jan@example.nl")).locale).toBe("zh");
    }, AS_WEB));

  it("sends at most 3 confirmation emails per address per day", () =>
    withRollback(async (tx) => {
      const outcomes = [];
      for (const m of [0, 11, 22, 33]) outcomes.push(await requestSubscription(deps(tx, minutes(m)), request, null));
      expect(outcomes).toEqual(["sent", "sent", "sent", "throttled"]);
    }, AS_WEB));

  it("lets an unsubscribed address subscribe again", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      await tx.execute(sql`UPDATE subscriptions SET status = 'unsubscribed', unsubscribed_at = now()
        WHERE email = 'jan@example.nl'`);
      const again = deps(tx, minutes(1));
      expect(await requestSubscription(again, request, null)).toBe("sent");
      const rows = await tx.execute(sql`SELECT status FROM subscriptions WHERE email = 'jan@example.nl' ORDER BY status`);
      expect(rows.map((r) => r.status)).toEqual(["pending", "unsubscribed"]);
    }, AS_WEB));
});

describe("database privileges (spec §11.2)", () => {
  it("lets the web role read but not write email_deliveries, except through the confirm function", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      const { id } = await subscriptionRow(tx, "jan@example.nl");
      expect(
        await pgErrorCode(tx, (sp) =>
          sp.execute(sql`INSERT INTO email_deliveries (subscription_id, kind) VALUES (${id}, 'digest')`),
        ),
      ).toBe("42501");
      expect(await pgErrorCode(tx, (sp) => sp.execute(sql`UPDATE email_deliveries SET provider_message_id = 'x'`))).toBe("42501");
      expect(await pgErrorCode(tx, (sp) => sp.execute(sql`DELETE FROM email_deliveries`))).toBe("42501");
      // Deleting a Subscription takes its deliveries with it (ticket 29, "delete my data").
      await tx.execute(sql`DELETE FROM subscriptions WHERE id = ${id}`);
      expect(await tx.execute(sql`SELECT 1 FROM email_deliveries WHERE subscription_id = ${id}`)).toHaveLength(0);
    }, AS_WEB));

  it("records confirm deliveries only for pending Subscriptions", () =>
    withRollback(async (tx) => {
      const d = deps(tx);
      await requestSubscription(d, request, null);
      await confirmSubscription(d, tokenFrom(d.transport.sent[0]));
      const { id } = await subscriptionRow(tx, "jan@example.nl");
      const [row] = await tx.execute(sql`SELECT record_confirm_delivery(${id}::uuid, 'm') AS id`);
      expect(row.id).toBeNull();
    }, AS_WEB));

  it("keeps the pipeline role out of the private tables", () =>
    withRollback(async (tx) => {
      for (const table of ["subscriptions", "email_suppressions", "email_deliveries"]) {
        expect(await pgErrorCode(tx, (sp) => sp.execute(sql.raw(`SELECT 1 FROM ${table}`)))).toBe("42501");
      }
      expect(
        await pgErrorCode(tx, (sp) => sp.execute(sql`SELECT record_confirm_delivery(gen_random_uuid(), 'm')`)),
      ).toBe("42501");
    }, { role: "ofa_pipeline" }));

  it("lets the mailer read Subscriptions and record deliveries, but not change Subscriptions", () =>
    withRollback(async (tx) => {
      await tx.execute(sql`SELECT count(*) FROM subscriptions`);
      await tx.execute(sql`SELECT count(*) FROM email_suppressions`);
      await tx.execute(sql`SELECT count(*) FROM notifications`);
      expect(await pgErrorCode(tx, (sp) => sp.execute(sql`UPDATE subscriptions SET locale = 'en'`))).toBe("42501");
      expect(await pgErrorCode(tx, (sp) => sp.execute(sql`DELETE FROM email_suppressions`))).toBe("42501");
      // INSERT is allowed (fails here only on the foreign key, not on privileges).
      expect(
        await pgErrorCode(tx, (sp) =>
          sp.execute(sql`INSERT INTO email_deliveries (subscription_id, kind) VALUES (gen_random_uuid(), 'digest')`),
        ),
      ).toBe("23503");
    }, { role: "ofa_mailer" }));
});
