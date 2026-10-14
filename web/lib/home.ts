/**
 * Data for the home page (spec §9): the Notifications published in the last 7 days per
 * Source. Same scope and date filter as search (spec §4.3: RASFF News included), so the
 * "all … in search" link shows exactly the Notifications counted here.
 */
import { sql } from "drizzle-orm";
import { filtersSql, FROM_NOTIFICATIONS, rows, scopeSql } from "./filter-sql";
import { NO_FILTERS, SOURCES, toSearchParams, type FilterSource } from "./filters";
import { notificationPath } from "./notification-path";
import type { Reader } from "./notifications";
import { SOURCE_LABELS } from "./search";

export const RECENT_DAYS = 7;

export type RecentItem = {
  source: FilterSource;
  sourceKey: string;
  path: string;
  title: string;
  /** ISO 8601 */
  publishedAt: string;
  notificationType: string;
};

export type RecentSource = {
  source: FilterSource;
  label: string;
  /** Notifications of this Source in the window. */
  total: number;
  /** The newest `perSource`, newest first. */
  items: RecentItem[];
  /** The search page with all of them. */
  searchPath: string;
};

export type RecentResponse = {
  /** First and last Amsterdam calendar day of the window, YYYY-MM-DD. */
  from: string;
  to: string;
  /** Always rasff, nvwa, openfda. */
  sources: RecentSource[];
};

const AMSTERDAM_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Amsterdam",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function addDays(day: string, delta: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

export async function getRecentNotifications(
  db: Reader,
  options: { locale: string; now?: Date; perSource?: number },
): Promise<RecentResponse> {
  const { locale, perSource = 5 } = options;
  const to = AMSTERDAM_DAY.format(options.now ?? new Date());
  const from = addDays(to, -(RECENT_DAYS - 1));
  const filters = { ...NO_FILTERS, from };
  const found = await rows<{
    source: FilterSource;
    source_key: string;
    title: string;
    published_at: string | Date;
    notification_type: string;
    rank: number;
    total: number;
  }>(
    db,
    sql`SELECT * FROM (
          SELECT s.code AS source, n.source_key, n.title, n.published_at, n.notification_type,
                 row_number() OVER (PARTITION BY s.code ORDER BY n.published_at DESC, n.id DESC)::int AS rank,
                 count(*) OVER (PARTITION BY s.code)::int AS total
          FROM ${FROM_NOTIFICATIONS}
          WHERE ${scopeSql("search")} AND ${filtersSql(filters)}
        ) r
        WHERE r.rank <= ${perSource}
        ORDER BY r.source, r.rank`,
  );
  return {
    from,
    to,
    sources: SOURCES.map((source) => {
      const mine = found.filter((r) => r.source === source);
      return {
        source,
        label: SOURCE_LABELS[source],
        total: mine[0]?.total ?? 0,
        items: mine.map((r) => ({
          source,
          sourceKey: r.source_key,
          path: notificationPath(locale, source, r.source_key),
          title: r.title,
          publishedAt: new Date(r.published_at).toISOString(),
          notificationType: r.notification_type,
        })),
        searchPath: `/${locale}/search?${toSearchParams({
          q: "",
          page: 1,
          filters: { ...filters, sources: [source] },
        }).toString()}`,
      };
    }),
  };
}
