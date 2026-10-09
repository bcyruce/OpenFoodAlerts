// Integration tests against TEST_DATABASE_URL (migrated by `make test-db`). Every test
// writes its rows inside a transaction that is rolled back, so the database stays clean.
import { sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { afterAll, describe, expect, it } from "vitest";
import { getNotificationDetail } from "./notifications";

const client = postgres(
  process.env.TEST_DATABASE_URL ?? "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable",
  { max: 1, onnotice: () => {} },
);
const db = drizzle(client);

afterAll(() => client.end());

type Tx = Parameters<Parameters<typeof db.transaction>[0]>[0];

class Rollback extends Error {}

async function withRollback(fn: (tx: Tx) => Promise<void>): Promise<void> {
  try {
    await db.transaction(async (tx) => {
      await fn(tx);
      throw new Rollback();
    });
  } catch (e) {
    if (!(e instanceof Rollback)) throw e;
  }
}

type Row = {
  key: string;
  productType?: string | null;
  provenance?: string;
  risk?: string | null;
};

/** One openFDA Notification as the pipeline writes it, with the given versions. */
async function insertNotification(
  tx: Tx,
  { key, productType = "food", provenance = "rule", risk = "Class II" }: Row,
  versions: { observedAt: string; changedFields: object; isSubstantial: boolean }[] = [
    { observedAt: "2026-10-15T08:00:00Z", changedFields: {}, isSubstantial: false },
  ],
): Promise<void> {
  const [raw] = await tx.execute<{ id: number }>(sql`
    INSERT INTO raw_records (source_id, source_key, kind, url, http_status, content_hash, content_type, body)
    VALUES (3, ${key}, 'detail', 'https://api.fda.gov/food/enforcement.json', 200, 'x', 'application/json', '\\x7b7d')
    RETURNING id`);
  const last = versions[versions.length - 1];
  const [n] = await tx.execute<{ id: number }>(sql`
    INSERT INTO notifications (
      source_id, source_key, source_url, source_ref, title, published_at, first_seen_at,
      last_changed_at, notification_type, risk_official, status_official, product_type,
      product_type_provenance, product_text, hazard_text, source_fields, raw_record_id,
      parser_version, current_version)
    VALUES (
      3, ${key}, ${"https://api.fda.gov/food/enforcement.json?search=recall_number:" + key},
      '99933', 'QUESO PALMITA', '2026-10-14T04:00:00Z', ${versions[0].observedAt},
      ${last.observedAt}, 'enforcement report', ${risk}, 'Completed', ${productType},
      ${provenance}, 'QUESO PALMITA. Generic Name: Pastel de Queso', 'Undeclared milk',
      ${JSON.stringify({ recalling_firm: "QUESO PALMITA GP LLC", report_date: "2026-10-14" })}::jsonb,
      ${raw.id}, 'openfda-3', ${versions.length})
    RETURNING id`);
  for (const [i, v] of versions.entries()) {
    await tx.execute(sql`
      INSERT INTO notification_versions
        (notification_id, version, raw_record_id, observed_at, changed_fields, is_substantial)
      VALUES (${n.id}, ${i + 1}, ${raw.id}, ${v.observedAt},
              ${JSON.stringify(v.changedFields)}::jsonb, ${v.isSubstantial})`);
  }
}

describe("getNotificationDetail", () => {
  it("returns the official fields, Source attribution and timestamps", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "H-0015-2027" });
      const n = await getNotificationDetail(tx, "openfda", "H-0015-2027");
      expect(n).not.toBeNull();
      expect(n).toMatchObject({
        sourceKey: "H-0015-2027",
        title: "QUESO PALMITA",
        notificationType: "enforcement report",
        riskOfficial: "Class II",
        statusOfficial: "Completed",
        productType: "food",
        productTypeProvenance: "rule",
        hazardText: "Undeclared milk",
        publishedAt: "2026-10-14T04:00:00.000Z",
        firstSeenAt: "2026-10-15T08:00:00.000Z",
        lastChangedAt: "2026-10-15T08:00:00.000Z",
        sourceFields: { recalling_firm: "QUESO PALMITA GP LLC", report_date: "2026-10-14" },
        source: {
          code: "openfda",
          name: "openFDA food enforcement reports",
          attributionText:
            "Source: U.S. Food and Drug Administration via openFDA. Not endorsed by FDA.",
        },
      });
      expect(n?.sourceUrl).toContain("H-0015-2027");
    }));

  it("lists versions newest first with their field changes", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "H-0015-2027" }, [
        { observedAt: "2026-10-15T08:00:00Z", changedFields: {}, isSubstantial: false },
        {
          observedAt: "2026-10-22T08:00:00Z",
          changedFields: {
            status_official: { old: "Ongoing", new: "Completed" },
            "source_fields.distribution_pattern": { old: "Texas", new: "Texas and Louisiana" },
          },
          isSubstantial: true,
        },
      ]);
      const n = await getNotificationDetail(tx, "openfda", "H-0015-2027");
      expect(n?.versions).toEqual([
        {
          version: 2,
          observedAt: "2026-10-22T08:00:00.000Z",
          isSubstantial: true,
          changes: [
            { field: "source_fields.distribution_pattern", old: "Texas", new: "Texas and Louisiana" },
            { field: "status_official", old: "Ongoing", new: "Completed" },
          ],
        },
        { version: 1, observedAt: "2026-10-15T08:00:00.000Z", isSubstantial: false, changes: [] },
      ]);
    }));

  it.each([
    ["food", "rule"],
    ["feed", "rule"],
    ["food contact material", "official"],
  ])("shows Product type %s", (productType, provenance) =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "K-1", productType, provenance });
      expect(await getNotificationDetail(tx, "openfda", "K-1")).not.toBeNull();
    }),
  );

  it("hides non-food Notifications", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "K-1", productType: "non-food" });
      expect(await getNotificationDetail(tx, "openfda", "K-1")).toBeNull();
    }));

  it("hides Notifications whose Product type waits for T5", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "K-1", productType: null, provenance: "pending" });
      expect(await getNotificationDetail(tx, "openfda", "K-1")).toBeNull();
    }));

  it("returns null for an unknown key or a key under another Source", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "H-0015-2027" });
      expect(await getNotificationDetail(tx, "openfda", "H-9999-2027")).toBeNull();
      expect(await getNotificationDetail(tx, "rasff", "H-0015-2027")).toBeNull();
    }));

  it("keeps a missing official severity as null (shown as not graded)", () =>
    withRollback(async (tx) => {
      await insertNotification(tx, { key: "K-1", risk: null });
      expect((await getNotificationDetail(tx, "openfda", "K-1"))?.riskOfficial).toBeNull();
    }));
});
