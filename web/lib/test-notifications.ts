// Test-only: Notifications as the pipeline writes them, for integration tests against
// TEST_DATABASE_URL. `withNotifications` deletes every Notification and inserts the given
// rows inside a transaction that is rolled back, so neither leftovers from pipeline tests
// nor these rows leak.
import { sql } from "drizzle-orm";
import { withRollback, type Tx } from "./test-db";

export const SOURCE_IDS = { rasff: 1, nvwa: 2, openfda: 3 } as const;

// Seeded RASFF dictionary ids.
export const ALLERGENS = 21798;
export const PATHOGENS = 21801;
export const PESTICIDES = 21795;
export const MILK_PRODUCTS = 18454; // "milk and milk products"
export const HERBS = 18450; // "herbs and spices"

export type Row = {
  source: keyof typeof SOURCE_IDS;
  key: string;
  title: string;
  publishedAt?: string | null;
  notificationType?: string;
  risk?: string | null;
  productType?: string | null;
  productTypeProvenance?: string;
  productText?: string | null;
  hazardText?: string | null;
  hazards?: { name: string; category: number; provenance?: "official" | "ai" }[];
  productCategories?: { category: number; provenance?: "official" | "ai" }[];
  countries?: { iso2: string; role?: string; provenance?: "official" | "ai" }[];
};

export async function withNotifications(rows: Row[], fn: (tx: Tx) => Promise<void>): Promise<void> {
  await withRollback(async (tx) => {
    await tx.execute(sql`DELETE FROM notifications`);
    for (const row of rows) await insertNotification(tx, row);
    await fn(tx);
  });
}

/** One Notification as the pipeline writes it, search_tsv included. */
export async function insertNotification(tx: Tx, r: Row): Promise<void> {
  const sid = SOURCE_IDS[r.source];
  const [raw] = await tx.execute<{ id: number }>(sql`
    INSERT INTO raw_records (source_id, source_key, kind, url, http_status, content_hash, content_type, body)
    VALUES (${sid}, ${r.key}, 'detail', 'https://example.test', 200, 'x', 'application/json', '\\x7b7d')
    RETURNING id`);
  const productType = r.productType === undefined ? "food" : r.productType;
  const provenance =
    r.productTypeProvenance ??
    (productType === null ? "pending" : r.source === "rasff" ? "official" : "rule");
  const [n] = await tx.execute<{ id: number }>(sql`
    INSERT INTO notifications (
      source_id, source_key, source_url, title, published_at, notification_type,
      risk_official, product_type, product_type_provenance, product_text, hazard_text,
      raw_record_id, parser_version)
    VALUES (
      ${sid}, ${r.key}, ${"https://example.test/" + r.key}, ${r.title},
      ${r.publishedAt === undefined ? "2026-10-01T10:00:00Z" : r.publishedAt},
      ${r.notificationType ?? "alert notification"}, ${r.risk ?? null}, ${productType},
      ${provenance}, ${r.productText ?? null}, ${r.hazardText ?? null}, ${raw.id}, 'test-1')
    RETURNING id`);
  for (const [i, h] of (r.hazards ?? []).entries()) {
    await tx.execute(sql`
      INSERT INTO notification_hazards (notification_id, position, hazard_name, hazard_category_id, provenance)
      VALUES (${n.id}, ${i}, ${h.name},
              (SELECT id FROM hazard_categories WHERE rasff_id = ${h.category}),
              ${h.provenance ?? "official"})`);
  }
  for (const [i, c] of (r.productCategories ?? []).entries()) {
    await tx.execute(sql`
      INSERT INTO notification_product_categories (notification_id, position, product_category_id, provenance)
      VALUES (${n.id}, ${i}, (SELECT id FROM product_categories WHERE rasff_id = ${c.category}),
              ${c.provenance ?? "official"})`);
  }
  for (const c of r.countries ?? []) {
    await tx.execute(sql`
      INSERT INTO notification_countries (notification_id, country_iso2, role, provenance)
      VALUES (${n.id}, ${c.iso2}, ${c.role ?? "origin"}, ${c.provenance ?? "official"})`);
  }
  await tx.execute(
    sql`UPDATE notifications SET search_tsv = notification_search_tsv(id) WHERE id = ${n.id}`,
  );
}
