/**
 * Source health for `/api/health` (spec §8, §13). Server-only; pass the database (the
 * read-only `ofa_web` role in production) and the current time explicitly.
 *
 * A Source is healthy when all of these hold:
 * - fresh: its last successful ingest run (`sources.last_success_at`, written by the
 *   pipeline's ingest jobs whether or not they found anything new) is at most
 *   FRESH_HOURS old;
 * - its last contract probe (`ofa probe-contracts`, daily) passed and is at most
 *   CONTRACT_MAX_AGE_HOURS old;
 * - RASFF only: at least one new Notification (by `first_seen_at`) in the last
 *   RASFF_SILENCE_DAYS days. RASFF publishes every working day, so a silent week almost
 *   certainly means a broken endpoint; NVWA and openFDA have normal quiet weeks.
 *
 * The text of `sources.last_error` is never exposed (an httpx error message can carry a
 * URL with the openFDA API key); only its timestamp is. The contract error is a short
 * message the probe writes with field paths and HTTP statuses only.
 */
import { asc, count, eq, gte, max } from "drizzle-orm";
import { notifications, sources } from "@/db/generated/schema";
import type { Reader } from "./notifications";

export const FRESH_HOURS = 36;
export const CONTRACT_MAX_AGE_HOURS = 36;
export const RASFF_SILENCE_DAYS = 7;

const HOUR_MS = 3600_000;

export type ContractStatus = "ok" | "failed" | "unreachable" | "unchecked";

export type HealthProblem =
  | "never_succeeded"
  | "stale"
  | "contract_failed"
  | "contract_unreachable"
  | "contract_unchecked"
  | "contract_stale"
  | "silent";

export type SourceHealth = {
  source: string;
  name: string;
  ok: boolean;
  /** Empty when ok; in the order of the checks above. */
  problems: HealthProblem[];
  /** ISO 8601 or null. */
  lastSuccessAt: string | null;
  lastErrorAt: string | null;
  fresh: boolean;
  contract: { status: ContractStatus; checkedAt: string | null; error: string | null };
  /** Notifications first seen in the last RASFF_SILENCE_DAYS days (every Source). */
  newNotifications: { days: number; count: number; lastFirstSeenAt: string | null };
  /** RASFF only: no new Notification in that window. Always false for other Sources. */
  silent: boolean;
};

export type Health = {
  status: "ok" | "degraded";
  /** ISO 8601 */
  checkedAt: string;
  thresholds: { freshHours: number; rasffSilenceDays: number };
  sources: SourceHealth[];
};

function iso(value: string | null): string | null {
  return value === null ? null : new Date(value).toISOString();
}

function olderThan(value: string | null, hours: number, now: Date): boolean {
  return value === null || now.getTime() - new Date(value).getTime() > hours * HOUR_MS;
}

function contractStatus(value: string | null): ContractStatus {
  return value === "ok" || value === "failed" || value === "unreachable" ? value : "unchecked";
}

export async function getHealth(db: Reader, now: Date): Promise<Health> {
  const since = new Date(now.getTime() - RASFF_SILENCE_DAYS * 24 * HOUR_MS).toISOString();
  const rows = await db
    .select({
      code: sources.code,
      name: sources.name,
      lastSuccessAt: sources.lastSuccessAt,
      lastErrorAt: sources.lastErrorAt,
      contractStatus: sources.contractStatus,
      contractCheckedAt: sources.contractCheckedAt,
      contractError: sources.contractError,
    })
    .from(sources)
    .orderBy(asc(sources.id));
  const latest = await db
    .select({ code: sources.code, lastFirstSeenAt: max(notifications.firstSeenAt) })
    .from(notifications)
    .innerJoin(sources, eq(sources.id, notifications.sourceId))
    .groupBy(sources.code);
  const recent = await db
    .select({ code: sources.code, count: count() })
    .from(notifications)
    .innerJoin(sources, eq(sources.id, notifications.sourceId))
    .where(gte(notifications.firstSeenAt, since))
    .groupBy(sources.code);
  const lastSeen = new Map(latest.map((r) => [r.code, r.lastFirstSeenAt]));
  const recentCount = new Map(recent.map((r) => [r.code, r.count]));

  const result = rows.map((r): SourceHealth => {
    const problems: HealthProblem[] = [];
    const fresh = !olderThan(r.lastSuccessAt, FRESH_HOURS, now);
    if (r.lastSuccessAt === null) problems.push("never_succeeded");
    else if (!fresh) problems.push("stale");
    const status = contractStatus(r.contractStatus);
    if (status === "failed") problems.push("contract_failed");
    else if (status === "unreachable") problems.push("contract_unreachable");
    else if (status === "unchecked") problems.push("contract_unchecked");
    else if (olderThan(r.contractCheckedAt, CONTRACT_MAX_AGE_HOURS, now))
      problems.push("contract_stale");
    const newCount = recentCount.get(r.code) ?? 0;
    const silent = r.code === "rasff" && newCount === 0;
    if (silent) problems.push("silent");
    return {
      source: r.code,
      name: r.name,
      ok: problems.length === 0,
      problems,
      lastSuccessAt: iso(r.lastSuccessAt),
      lastErrorAt: iso(r.lastErrorAt),
      fresh,
      contract: {
        status,
        checkedAt: iso(r.contractCheckedAt),
        error: status === "ok" || status === "unchecked" ? null : r.contractError,
      },
      newNotifications: {
        days: RASFF_SILENCE_DAYS,
        count: newCount,
        lastFirstSeenAt: iso(lastSeen.get(r.code) ?? null),
      },
      silent,
    };
  });
  return {
    status: result.every((s) => s.ok) ? "ok" : "degraded",
    checkedAt: now.toISOString(),
    thresholds: { freshHours: FRESH_HOURS, rasffSilenceDays: RASFF_SILENCE_DAYS },
    sources: result,
  };
}

/** 200 when every Source is healthy, else 503 (for uptime monitors, spec §8). */
export function healthStatusCode(health: Health): 200 | 503 {
  return health.status === "ok" ? 200 : 503;
}
