/**
 * Data for `/zh/jinggao` (spec §9, ticket 33): NVWA safety warnings about food, newest
 * first, each with its Chinese T6 summary (spec §6.1, AI-generated) when there is one.
 * Server-only; the database is passed in. Two queries per page, whatever its length: the
 * page of Notifications with the total, then their summaries (`getAiSummaries`).
 *
 * NVWA does not grade its warnings: there is no severity here at all (ADR 0006).
 */
import { sql } from "drizzle-orm";
import { getAiSummaries, type AiSummary } from "./ai";
import { FROM_NOTIFICATIONS, rows } from "./filter-sql";
import { notificationPath } from "./notification-path";
import type { Reader } from "./notifications";

/**
 * Warnings per page. The smoke tests set `OFA_ZH_WARNINGS_PAGE_SIZE` (build and server)
 * because the fixtures hold fewer than one page; a deployment leaves it unset.
 */
export const ZH_WARNINGS_PAGE_SIZE = Number(process.env.OFA_ZH_WARNINGS_PAGE_SIZE) || 20;

/**
 * Detail pages exist in en and nl only (spec §9); the stream links the English one, the
 * language more Chinese-speaking readers in the Netherlands read than Dutch.
 */
export const ZH_WARNINGS_DETAIL_LOCALE = "en";

export type ZhWarning = {
  id: number;
  sourceKey: string;
  /** The official Dutch title. */
  title: string;
  /** ISO 8601 */
  publishedAt: string | null;
  /** The warning on nvwa.nl. */
  sourceUrl: string;
  /** This site's detail page, in ZH_WARNINGS_DETAIL_LOCALE. */
  detailPath: string;
  /** NVWA withdrew the warning (ticket 09: status_official = withdrawn). */
  withdrawn: boolean;
  /** The Chinese T6 summary; null when there is none (not generated yet, or abstained). */
  summary: AiSummary | null;
};

export type ZhWarningsPage = {
  page: number;
  pageSize: number;
  total: number;
  /** At least 1: an empty stream still has its first page. */
  totalPages: number;
  items: ZhWarning[];
};

/**
 * One page of the stream (1-based), or null for a page past the last. Scope: Source NVWA
 * and Product type food (not feed, food contact material, non-food or pending).
 */
export async function getZhWarnings(
  db: Reader,
  { page, pageSize = ZH_WARNINGS_PAGE_SIZE }: { page: number; pageSize?: number },
): Promise<ZhWarningsPage | null> {
  const found = await rows<{
    id: number | string;
    source_key: string;
    title: string;
    published_at: string | Date | null;
    source_url: string;
    status_official: string | null;
    total: number;
  }>(
    db,
    sql`SELECT n.id, n.source_key, n.title, n.published_at, n.source_url, n.status_official,
               count(*) OVER ()::int AS total
        FROM ${FROM_NOTIFICATIONS}
        WHERE s.code = 'nvwa' AND n.product_type = 'food'
        ORDER BY n.published_at DESC NULLS LAST, n.id DESC
        LIMIT ${pageSize} OFFSET ${(page - 1) * pageSize}`,
  );
  // The total comes with the rows; a page without rows is either the empty first page or
  // past the end.
  if (found.length === 0 && page > 1) return null;
  const total = found[0]?.total ?? 0;
  const summaries = await getAiSummaries(
    db,
    found.map((r) => Number(r.id)),
    "zh",
  );
  return {
    page,
    pageSize,
    total,
    totalPages: Math.max(1, Math.ceil(total / pageSize)),
    items: found.map((r) => {
      const id = Number(r.id);
      return {
        id,
        sourceKey: r.source_key,
        title: r.title,
        publishedAt: r.published_at === null ? null : new Date(r.published_at).toISOString(),
        sourceUrl: r.source_url,
        detailPath: notificationPath(ZH_WARNINGS_DETAIL_LOCALE, "nvwa", r.source_key),
        withdrawn: r.status_official === "withdrawn",
        summary: summaries.get(id) ?? null,
      };
    }),
  };
}

/** Upper bound for a page number in a URL, far beyond any real page. */
const MAX_PAGE = 100_000;

/**
 * The page number in `/zh/jinggao/{page}`: canonical integers from 2 (page 1 is
 * `/zh/jinggao` itself), else null (a 404), so every page has exactly one URL.
 */
export function parseZhWarningsPage(segment: string): number | null {
  if (!/^[1-9]\d*$/.test(segment)) return null;
  const page = Number(segment);
  return page >= 2 && page <= MAX_PAGE ? page : null;
}

/** The URL of a page of the stream. */
export function zhWarningsPath(page: number): string {
  return page <= 1 ? "/zh/jinggao" : `/zh/jinggao/${page}`;
}
