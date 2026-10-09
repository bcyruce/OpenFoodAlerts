/**
 * Read access to Notifications for display (spec §4.3, §9). Server-only; pass the
 * database explicitly so callers decide on caching and tests can use a transaction.
 */
import { and, desc, eq, inArray } from "drizzle-orm";
import type { PgDatabase, PgQueryResultHKT } from "drizzle-orm/pg-core";
import { notifications, notificationVersions, sources } from "@/db/generated/schema";

/** A database or transaction that can run selects. */
export type Reader = PgDatabase<PgQueryResultHKT>;

/** Only these Product types appear on pages; non-food and pending (T5) do not. */
export const DISPLAYED_PRODUCT_TYPES = ["food", "feed", "food contact material"] as const;
export type DisplayedProductType = (typeof DISPLAYED_PRODUCT_TYPES)[number];

export type FieldChange = { field: string; old: unknown; new: unknown };

export type NotificationVersion = {
  version: number;
  /** ISO 8601 */
  observedAt: string;
  isSubstantial: boolean;
  /** Sorted by field name; `source_fields.<key>` for Source-specific fields. */
  changes: FieldChange[];
};

export type NotificationDetail = {
  id: number;
  source: { code: string; name: string; license: string; attributionText: string };
  sourceKey: string;
  sourceUrl: string;
  sourceRef: string | null;
  title: string;
  /** Timestamps are ISO 8601 strings. */
  publishedAt: string | null;
  sourceUpdatedAt: string | null;
  firstSeenAt: string;
  lastChangedAt: string;
  notificationType: string;
  /** RASFF risk decision or FDA classification; null means the Source does not grade. */
  riskOfficial: string | null;
  statusOfficial: string | null;
  productType: DisplayedProductType;
  productTypeProvenance: string;
  productText: string | null;
  hazardText: string | null;
  summarySource: string | null;
  /** Source-specific official fields, e.g. FDA `recalling_firm`; dates as YYYY-MM-DD. */
  sourceFields: Record<string, unknown>;
  currentVersion: number;
  /** Newest first. */
  versions: NotificationVersion[];
};

function iso(value: string): string;
function iso(value: string | null): string | null;
function iso(value: string | null): string | null {
  return value === null ? null : new Date(value).toISOString();
}

function toChanges(changedFields: unknown): FieldChange[] {
  if (changedFields === null || typeof changedFields !== "object") return [];
  return Object.entries(changedFields as Record<string, { old?: unknown; new?: unknown }>)
    .map(([field, diff]) => ({ field, old: diff?.old ?? null, new: diff?.new ?? null }))
    .sort((a, b) => a.field.localeCompare(b.field));
}

/** The Notification with its version history, or null if it is missing or not shown. */
export async function getNotificationDetail(
  db: Reader,
  source: string,
  key: string,
): Promise<NotificationDetail | null> {
  const [row] = await db
    .select({
      n: notifications,
      source: {
        code: sources.code,
        name: sources.name,
        license: sources.license,
        attributionText: sources.attributionText,
      },
    })
    .from(notifications)
    .innerJoin(sources, eq(sources.id, notifications.sourceId))
    .where(
      and(
        eq(sources.code, source),
        eq(notifications.sourceKey, key),
        inArray(notifications.productType, [...DISPLAYED_PRODUCT_TYPES]),
      ),
    )
    .limit(1);
  if (!row) return null;
  const { n } = row;
  const versions = await db
    .select()
    .from(notificationVersions)
    .where(eq(notificationVersions.notificationId, n.id))
    .orderBy(desc(notificationVersions.version));
  return {
    id: n.id,
    source: row.source,
    sourceKey: n.sourceKey,
    sourceUrl: n.sourceUrl,
    sourceRef: n.sourceRef,
    title: n.title,
    publishedAt: iso(n.publishedAt),
    sourceUpdatedAt: iso(n.sourceUpdatedAt),
    firstSeenAt: iso(n.firstSeenAt),
    lastChangedAt: iso(n.lastChangedAt),
    notificationType: n.notificationType,
    riskOfficial: n.riskOfficial,
    statusOfficial: n.statusOfficial,
    productType: n.productType as DisplayedProductType,
    productTypeProvenance: n.productTypeProvenance,
    productText: n.productText,
    hazardText: n.hazardText,
    summarySource: n.summarySource,
    sourceFields: (n.sourceFields ?? {}) as Record<string, unknown>,
    currentVersion: n.currentVersion,
    versions: versions.map((v) => ({
      version: v.version,
      observedAt: iso(v.observedAt),
      isSubstantial: v.isSubstantial,
      changes: toChanges(v.changedFields),
    })),
  };
}

/** Most recently published shown Notifications, for prerendering at build time. */
export async function listRecentNotificationKeys(
  db: Reader,
  limit: number,
): Promise<{ source: string; key: string }[]> {
  return db
    .select({ source: sources.code, key: notifications.sourceKey })
    .from(notifications)
    .innerJoin(sources, eq(sources.id, notifications.sourceId))
    .where(inArray(notifications.productType, [...DISPLAYED_PRODUCT_TYPES]))
    .orderBy(desc(notifications.publishedAt), desc(notifications.id))
    .limit(limit);
}
