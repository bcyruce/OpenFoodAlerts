/**
 * The current AI classifications of Notifications (spec §6, §9 AI badge), for the detail
 * page and the search results. Server-only; the database is passed in.
 *
 * Rows of `ai_classifications` (migration 20261025001500, ticket 16) are append-only; per
 * Notification and task the current one is the newest (created_at, then id). The value
 * shown is `ai_effective_value(row)` (migration 20261025001600, ticket 20): a person's
 * correction, else the model's value, NULL for an abstention. A reviewed row (approved or
 * corrected; approving also writes reviewed_value) is badged "reviewed by a person".
 *
 * Shown tasks: T1 hazard_category, T3 hazard, T2 product_category, T4 origin_country.
 * T5 product_type is internal and never returned (spec §6.1). T6 summaries have one row
 * per locale and are read by `getAiSummary`.
 */
import { sql } from "drizzle-orm";
import { inList, rows } from "./filter-sql";
import type { Reader } from "./notifications";
import { categoryLabel, countryLabel, type Names } from "./search";

/** Shown AI tasks in display order (spec §6.1 names, as in `ai_classifications.task`). */
export const SHOWN_AI_TASKS = ["hazard_category", "hazard", "product_category", "origin_country"] as const;
export type ShownAiTask = (typeof SHOWN_AI_TASKS)[number];

/** T6 (ticket 18): one task per language, `summary_en`, `summary_nl`, `summary_zh`. */
export function summaryTask(locale: string): string {
  return `summary_${locale}`;
}

export function isSummaryTask(task: string): boolean {
  return task.startsWith("summary_");
}

/** T4's value when the source text names no country. */
export const UNKNOWN_COUNTRY = "unknown";

/** Who made an AI value and how: what the badge says. */
export type AiProvenance = {
  classificationId: number;
  task: string;
  model: string;
  promptVersion: string;
  /** ISO 8601 */
  createdAt: string;
  /** A person approved or corrected it (ticket 20). */
  reviewed: boolean;
};

export type AiField = AiProvenance & {
  task: ShownAiTask;
  /**
   * T1: a taxonomy label; T2: a Product category (RASFF id or name, as stored); T3: the
   * Hazard text span; T4: ISO2 or "unknown". null when the model abstained and nobody
   * filled in a value.
   */
  value: string | null;
  /** `value` for display: category and country names in the locale. */
  label: string | null;
  abstained: boolean;
  confidence: string | null;
};

/**
 * The keys a task's value object may carry its answer under, first match wins. T1 is
 * `{"category": ...}` (ticket 16); T2–T4 follow ticket 17, so the likely spellings are all
 * accepted until it is merged.
 */
const VALUE_KEYS: Record<ShownAiTask, string[]> = {
  hazard_category: ["category"],
  product_category: ["category"],
  hazard: ["hazard"],
  origin_country: ["country"],
};

type ClassificationRow = {
  id: number | string;
  notification_id: number | string;
  task: ShownAiTask;
  /** `ai_effective_value(a)` (ticket 20): the correction, else the model's value; null = abstain. */
  effective_value: unknown;
  review_status: string;
  reviewed: boolean;
  confidence: string | null;
  evidence_span: string | null;
  model: string;
  prompt_version: string;
  created_at: string | Date;
};

function json(value: unknown): Record<string, unknown> | null {
  const parsed = typeof value === "string" ? JSON.parse(value) : value;
  return parsed !== null && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
}

function readValue(task: ShownAiTask, value: Record<string, unknown> | null): string | null {
  for (const key of VALUE_KEYS[task]) {
    const v = value?.[key];
    if (typeof v === "string" && v.trim() !== "") return v.trim();
    if (typeof v === "number") return String(v);
  }
  return null;
}

/**
 * The current row of a (Notification, task): the newest by created_at, then id, the rule
 * the pipeline and `review_queue` use (ticket 20). A new prompt version or a changed
 * input always gives a newer row.
 */
const NEWEST = sql`a.created_at DESC, a.id DESC`;

/** A person looked at it: approving (ticket 20) also writes reviewed_value. */
const REVIEWED = sql`(a.review_status IN ('approved', 'corrected') OR a.reviewed_value IS NOT NULL)`;

type Catalog = Names & { key: string };

async function catalogs(db: Reader, countries: string[]) {
  const [hazards, products, places] = await Promise.all([
    rows<Catalog>(db, sql`SELECT lower(name_en) AS key, name_en, name_nl FROM hazard_categories`),
    rows<Catalog & { rasff_id: string }>(
      db,
      sql`SELECT lower(name_en) AS key, rasff_id::text AS rasff_id, name_en, name_nl
          FROM product_categories`,
    ),
    countries.length === 0
      ? Promise.resolve([] as Catalog[])
      : rows<Catalog>(
          db,
          sql`SELECT iso2 AS key, name_en, name_nl FROM countries WHERE iso2 IN (${inList(countries)})`,
        ),
  ]);
  return { hazards, products, places };
}

export type AiSummary = AiProvenance & { locale: string; text: string };

/**
 * The T6 summary of a Notification in `locale` (spec §6.1: NVWA en/nl/zh, FDA en/nl;
 * never RASFF), or null. See `getAiSummaries`.
 */
export async function getAiSummary(
  db: Reader,
  notificationId: number,
  locale: string,
): Promise<AiSummary | null> {
  return (await getAiSummaries(db, [notificationId], locale)).get(notificationId) ?? null;
}

/**
 * The T6 summaries in `locale` of several Notifications, in one query; ids without one are
 * absent. The single place that knows the T6 row shape (ticket 18): task
 * `summary_{locale}`, value `{"locale", "summary"}`; the newest row of that task counts,
 * through `ai_effective_value` (a correction wins, an abstention gives no summary), the
 * same rule as the Digest (`mail/summaries.py`).
 */
export async function getAiSummaries(
  db: Reader,
  notificationIds: number[],
  locale: string,
): Promise<Map<number, AiSummary>> {
  const out = new Map<number, AiSummary>();
  if (notificationIds.length === 0) return out;
  const task = summaryTask(locale);
  const found = await rows<{
    id: number | string;
    notification_id: number | string;
    summary: string | null;
    reviewed: boolean;
    model: string;
    prompt_version: string;
    created_at: string | Date;
  }>(
    db,
    sql`SELECT DISTINCT ON (a.notification_id)
          a.id, a.notification_id, ai_effective_value(a) ->> 'summary' AS summary,
          ${REVIEWED} AS reviewed, a.model, a.prompt_version, a.created_at
        FROM ai_classifications a
        WHERE a.notification_id IN (${inList(notificationIds)}) AND a.task = ${task}
        ORDER BY a.notification_id, ${NEWEST}`,
  );
  for (const row of found) {
    const text = row.summary?.trim();
    if (!text) continue;
    out.set(Number(row.notification_id), {
      classificationId: Number(row.id),
      task,
      locale,
      text,
      model: row.model,
      promptVersion: row.prompt_version,
      createdAt: new Date(row.created_at).toISOString(),
      reviewed: row.reviewed,
    });
  }
  return out;
}

/**
 * The current AI classification of each shown task, per Notification id, in
 * SHOWN_AI_TASKS order. Notifications without any are absent from the map.
 */
export async function getAiClassifications(
  db: Reader,
  notificationIds: number[],
  options: { locale: string },
): Promise<Map<number, AiField[]>> {
  const out = new Map<number, AiField[]>();
  if (notificationIds.length === 0) return out;
  const found = await rows<ClassificationRow>(
    db,
    sql`SELECT DISTINCT ON (a.notification_id, a.task)
          a.id, a.notification_id, a.task, ai_effective_value(a) AS effective_value,
          a.review_status, ${REVIEWED} AS reviewed, a.confidence, a.evidence_span, a.model,
          a.prompt_version, a.created_at
        FROM ai_classifications a
        WHERE a.notification_id IN (${inList(notificationIds)})
          AND a.task IN (${inList([...SHOWN_AI_TASKS])})
        ORDER BY a.notification_id, a.task, ${NEWEST}`,
  );
  const fields = found.map((r) => {
    const effective = json(r.effective_value);
    // T3's span may live only in evidence_span; a person's correction carries its own.
    const span =
      r.task === "hazard" && effective && r.review_status !== "corrected" ? r.evidence_span : null;
    return { r, value: readValue(r.task, effective) ?? span, reviewed: r.reviewed };
  });
  const countries = fields
    .filter((f) => f.r.task === "origin_country" && f.value && f.value !== UNKNOWN_COUNTRY)
    .map((f) => f.value!.toUpperCase());
  const { hazards, products, places } = await catalogs(db, [...new Set(countries)]);
  const label = (task: ShownAiTask, value: string): string => {
    switch (task) {
      case "hazard_category": {
        const c = hazards.find((h) => h.key === value.toLowerCase());
        return c ? categoryLabel(options.locale, c) : value;
      }
      case "product_category": {
        const c = products.find((p) => p.rasff_id === value || p.key === value.toLowerCase());
        return c ? categoryLabel(options.locale, c) : value;
      }
      case "origin_country": {
        if (value === UNKNOWN_COUNTRY) return value;
        const c = places.find((p) => p.key === value.toUpperCase());
        return countryLabel(options.locale, value.toUpperCase(), c ?? { name_en: value, name_nl: null });
      }
      case "hazard":
        return value;
    }
  };
  for (const { r, value, reviewed } of fields) {
    const id = Number(r.notification_id);
    const field: AiField = {
      task: r.task,
      value,
      label: value === null ? null : label(r.task, value),
      abstained: value === null,
      confidence: r.confidence,
      model: r.model,
      promptVersion: r.prompt_version,
      createdAt: new Date(r.created_at).toISOString(),
      reviewed,
      classificationId: Number(r.id),
    };
    out.set(id, [...(out.get(id) ?? []), field]);
  }
  for (const list of out.values()) {
    list.sort((a, b) => SHOWN_AI_TASKS.indexOf(a.task) - SHOWN_AI_TASKS.indexOf(b.task));
  }
  return out;
}
