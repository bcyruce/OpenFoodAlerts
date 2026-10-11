/**
 * SQL for the shared filters (`filters.ts`), for search and statistics alike. Conditions
 * apply to `notifications n JOIN sources s ON s.id = n.source_id` (see FROM_NOTIFICATIONS).
 *
 * Hazard category, Product category and origin country match official and AI rows alike
 * (spec §10.1); with `officialOnly` only rows with provenance = 'official' count (S3).
 * Official severity is always official (ADR 0006).
 */
import { sql, type SQL } from "drizzle-orm";
import { NOT_GRADED, type Filters } from "./filters";
import { DISPLAYED_PRODUCT_TYPES, type Reader } from "./notifications";

/** Filters that have a facet; `omit` leaves one out to count its values. */
export type FilterFacet = "source" | "hazard" | "product" | "country" | "risk";

export const FROM_NOTIFICATIONS = sql`notifications n JOIN sources s ON s.id = n.source_id`;

/**
 * Which Notifications may appear (spec §4.3): food, feed and food contact material only;
 * statistics also leave out RASFF News, search shows it.
 */
export function scopeSql(scope: "search" | "stats"): SQL {
  const shown = sql`n.product_type IN (${inList([...DISPLAYED_PRODUCT_TYPES])})`;
  return scope === "search"
    ? shown
    : sql`${shown} AND NOT (s.code = 'rasff' AND n.notification_type = 'news')`;
}

/** `AND <alias>.provenance = 'official'` when only official values count, else nothing. */
export function provenanceSql(alias: string, filters: Filters): SQL {
  return filters.officialOnly ? sql`AND ${sql.raw(alias)}.provenance = 'official'` : sql``;
}

/** All set filters ANDed together (TRUE when none is set). */
export function filtersSql(filters: Filters, options: { omit?: FilterFacet } = {}): SQL {
  const f = filters;
  const omit = options.omit;
  const conditions: SQL[] = [];
  if (omit !== "source" && f.sources.length > 0) {
    conditions.push(sql`s.code IN (${inList(f.sources)})`);
  }
  if (omit !== "hazard" && f.hazardCategories.length > 0) {
    conditions.push(sql`EXISTS (
      SELECT 1 FROM notification_hazards h
      JOIN hazard_categories hc ON hc.id = h.hazard_category_id
      WHERE h.notification_id = n.id AND hc.rasff_id IN (${inList(f.hazardCategories)})
        ${provenanceSql("h", f)})`);
  }
  if (omit !== "product" && f.productCategories.length > 0) {
    conditions.push(sql`EXISTS (
      SELECT 1 FROM notification_product_categories pc
      JOIN product_categories p ON p.id = pc.product_category_id
      WHERE pc.notification_id = n.id AND p.rasff_id IN (${inList(f.productCategories)})
        ${provenanceSql("pc", f)})`);
  }
  if (omit !== "country" && f.countries.length > 0) {
    conditions.push(sql`EXISTS (
      SELECT 1 FROM notification_countries c
      WHERE c.notification_id = n.id AND c.role = 'origin'
        AND c.country_iso2 IN (${inList(f.countries)}) ${provenanceSql("c", f)})`);
  }
  if (omit !== "risk" && f.risks.length > 0) {
    const graded = f.risks.filter((r) => r !== NOT_GRADED);
    const parts: SQL[] = [];
    if (graded.length > 0) parts.push(sql`n.risk_official IN (${inList(graded)})`);
    if (f.risks.includes(NOT_GRADED)) parts.push(sql`n.risk_official IS NULL`);
    conditions.push(sql`(${sql.join(parts, sql` OR `)})`);
  }
  // Calendar days in Europe/Amsterdam; `to` is inclusive.
  if (f.from) {
    conditions.push(
      sql`n.published_at >= (${f.from}::date::timestamp AT TIME ZONE 'Europe/Amsterdam')`,
    );
  }
  if (f.to) {
    conditions.push(
      sql`n.published_at < ((${f.to}::date + 1)::timestamp AT TIME ZONE 'Europe/Amsterdam')`,
    );
  }
  return conditions.length > 0 ? sql.join(conditions, sql` AND `) : sql`TRUE`;
}

/** Comma-separated parameters for `IN (...)`. */
export function inList(values: readonly (string | number)[]): SQL {
  return sql.join(
    values.map((v) => sql`${v}`),
    sql`, `,
  );
}

/** Rows of a raw query, whichever driver the Reader uses. */
export async function rows<T>(db: Reader, query: SQL): Promise<T[]> {
  const result = (await db.execute(query)) as unknown;
  return (Array.isArray(result) ? result : (result as { rows: T[] }).rows) as T[];
}
