/**
 * The current AI classifications of Notifications (spec §6, §9 AI badge), for the detail
 * page and the search results. Server-only; the database is passed in.
 *
 * Rows of `ai_classifications` (migration 20261025001500, ticket 16) are append-only; per
 * Notification and task the current one is the latest prompt version, then the newest row.
 * A person's review (ticket 20) wins: `reviewed_value`, when set, replaces the model's
 * value, and a reviewed row (approved or corrected) is badged "reviewed by a person".
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

/** T6; the name ticket 30 proposed (`mail/summaries.py`). Ticket 18 decides. */
export const SUMMARY_TASK = "t6_summary";

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
  product_category: ["category", "product_category"],
  hazard: ["hazard", "span", "text"],
  origin_country: ["country", "iso2", "origin_country"],
};

type ClassificationRow = {
  id: number | string;
  notification_id: number | string;
  task: ShownAiTask;
  value: unknown;
  reviewed_value: unknown;
  review_status: string;
  abstained: boolean;
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

/** Prompt versions compare by number (v10 after v9), as the pipeline orders them. */
const ORDER = sql`a.notification_id, a.task,
  substring(a.prompt_version from '[0-9]+')::int DESC NULLS LAST, a.created_at DESC, a.id DESC`;

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
 * never RASFF), or null. The single place that knows the T6 row shape, proposed by ticket
 * 30 and to be settled by ticket 18: task SUMMARY_TASK, value `{"locale", "summary"}`, a
 * reviewer's `reviewed_value` of the same shape wins, abstained rows are skipped, and the
 * latest prompt version, then the newest row, per locale counts.
 */
export async function getAiSummary(
  db: Reader,
  notificationId: number,
  locale: string,
): Promise<AiSummary | null> {
  const [row] = await rows<{
    id: number | string;
    summary: string | null;
    reviewed: boolean;
    model: string;
    prompt_version: string;
    created_at: string | Date;
  }>(
    db,
    sql`SELECT a.id, coalesce(a.reviewed_value, a.value) ->> 'summary' AS summary,
          (a.review_status <> 'unreviewed' OR a.reviewed_value IS NOT NULL) AS reviewed,
          a.model, a.prompt_version, a.created_at
        FROM ai_classifications a
        WHERE a.notification_id = ${notificationId} AND a.task = ${SUMMARY_TASK}
          AND (NOT a.abstained OR a.reviewed_value IS NOT NULL)
          AND coalesce(a.reviewed_value, a.value) ->> 'locale' = ${locale}
        ORDER BY ${ORDER}
        LIMIT 1`,
  );
  if (!row?.summary?.trim()) return null;
  return {
    classificationId: Number(row.id),
    task: SUMMARY_TASK,
    locale,
    text: row.summary.trim(),
    model: row.model,
    promptVersion: row.prompt_version,
    createdAt: new Date(row.created_at).toISOString(),
    reviewed: row.reviewed,
  };
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
          a.id, a.notification_id, a.task, a.value, a.reviewed_value, a.review_status,
          a.abstained, a.confidence, a.evidence_span, a.model, a.prompt_version, a.created_at
        FROM ai_classifications a
        WHERE a.notification_id IN (${inList(notificationIds)})
          AND a.task IN (${inList([...SHOWN_AI_TASKS])})
        ORDER BY ${ORDER}`,
  );
  const fields = found.map((r) => {
    const reviewedValue = json(r.reviewed_value);
    const value =
      readValue(r.task, reviewedValue ?? json(r.value)) ??
      (r.task === "hazard" && !reviewedValue && !r.abstained ? r.evidence_span : null);
    return { r, value, reviewed: r.review_status !== "unreviewed" || reviewedValue !== null };
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
