// Integration tests against TEST_DATABASE_URL (migrated by `make test-db`). Every test
// changes the sources rows inside a transaction that is rolled back.
import { sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { afterAll, describe, expect, it } from "vitest";
import { getHealth, healthStatusCode, type Health } from "./health";

const TEST_URL =
  process.env.TEST_DATABASE_URL ?? "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable";
const client = postgres(TEST_URL, { max: 1, onnotice: () => {} });
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

const NOW = new Date("2026-10-25T12:00:00Z");
const HOURS_AGO = (h: number) => new Date(NOW.getTime() - h * 3600_000).toISOString();

type SourceState = {
  lastSuccessAt?: string | null;
  lastErrorAt?: string | null;
  lastError?: string | null;
  contractStatus?: string | null;
  contractCheckedAt?: string | null;
  contractError?: string | null;
};

async function setSource(tx: Tx, code: string, state: SourceState = {}): Promise<void> {
  const s = {
    lastSuccessAt: HOURS_AGO(2),
    lastErrorAt: null,
    lastError: null,
    contractStatus: "ok",
    contractCheckedAt: HOURS_AGO(3),
    contractError: null,
    ...state,
  };
  await tx.execute(sql`
    UPDATE sources SET last_success_at = ${s.lastSuccessAt}, last_error_at = ${s.lastErrorAt},
      last_error = ${s.lastError}, contract_status = ${s.contractStatus},
      contract_checked_at = ${s.contractCheckedAt}, contract_error = ${s.contractError}
    WHERE code = ${code}`);
}

/** A Notification of the given Source first seen at `firstSeenAt`. */
async function seen(tx: Tx, sourceId: number, key: string, firstSeenAt: string): Promise<void> {
  const [raw] = await tx.execute<{ id: number }>(sql`
    INSERT INTO raw_records (source_id, source_key, kind, url, http_status, content_hash, content_type, body)
    VALUES (${sourceId}, ${key}, 'detail', 'https://example.org/', 200, 'x', 'application/json', '\\x7b7d')
    RETURNING id`);
  await tx.execute(sql`
    INSERT INTO notifications (source_id, source_key, source_url, title, published_at,
      first_seen_at, last_changed_at, notification_type, product_type, product_type_provenance,
      raw_record_id, parser_version)
    VALUES (${sourceId}, ${key}, 'https://example.org/', 'T', ${firstSeenAt}, ${firstSeenAt},
      ${firstSeenAt}, 'alert notification', 'food', 'official', ${raw.id}, 'test')`);
}

/** Every Source fresh with a passing contract, and a RASFF Notification seen yesterday. */
async function healthy(tx: Tx): Promise<void> {
  for (const code of ["rasff", "nvwa", "openfda"]) await setSource(tx, code);
  await seen(tx, 1, "2026.9489", HOURS_AGO(20));
}

function source(health: Health, code: string) {
  const s = health.sources.find((x) => x.source === code);
  if (!s) throw new Error(`no ${code}`);
  return s;
}

describe("getHealth", () => {
  it("reports every Source as healthy when fresh, probed and not silent", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      const health = await getHealth(tx, NOW);
      expect(health.status).toBe("ok");
      expect(healthStatusCode(health)).toBe(200);
      expect(health.checkedAt).toBe("2026-10-25T12:00:00.000Z");
      expect(health.thresholds).toEqual({ freshHours: 36, rasffSilenceDays: 7 });
      expect(health.sources.map((s) => s.source)).toEqual(["rasff", "nvwa", "openfda"]);
      expect(source(health, "rasff")).toEqual({
        source: "rasff",
        name: "EU RASFF Window",
        ok: true,
        problems: [],
        lastSuccessAt: "2026-10-25T10:00:00.000Z",
        lastErrorAt: null,
        fresh: true,
        contract: { status: "ok", checkedAt: "2026-10-25T09:00:00.000Z", error: null },
        newNotifications: {
          days: 7,
          count: 1,
          lastFirstSeenAt: "2026-10-24T16:00:00.000Z",
        },
        silent: false,
      });
    }));

  it("marks a Source without a successful run in 36 hours as not fresh", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      await setSource(tx, "nvwa", { lastSuccessAt: HOURS_AGO(37), lastErrorAt: HOURS_AGO(1) });
      await setSource(tx, "openfda", { lastSuccessAt: HOURS_AGO(35) });
      const health = await getHealth(tx, NOW);
      expect(health.status).toBe("degraded");
      expect(healthStatusCode(health)).toBe(503);
      const nvwa = source(health, "nvwa");
      expect(nvwa).toMatchObject({ ok: false, fresh: false, problems: ["stale"] });
      expect(nvwa.lastErrorAt).toBe("2026-10-25T11:00:00.000Z");
      expect(source(health, "openfda")).toMatchObject({ ok: true, fresh: true });
    }));

  it("marks a Source that never succeeded", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      await setSource(tx, "openfda", { lastSuccessAt: null });
      expect(source(await getHealth(tx, NOW), "openfda")).toMatchObject({
        ok: false,
        fresh: false,
        lastSuccessAt: null,
        problems: ["never_succeeded"],
      });
    }));

  it("reports contract failures, unreachable, stale and missing probes", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      await setSource(tx, "rasff", {
        contractStatus: "failed",
        contractError: "detail: reference: Field required",
      });
      await setSource(tx, "nvwa", { contractStatus: "unreachable", contractError: "list: HTTP 503" });
      await setSource(tx, "openfda", { contractStatus: null, contractCheckedAt: null });
      const health = await getHealth(tx, NOW);
      expect(source(health, "rasff")).toMatchObject({
        ok: false,
        problems: ["contract_failed"],
        contract: { status: "failed", error: "detail: reference: Field required" },
      });
      expect(source(health, "nvwa").problems).toEqual(["contract_unreachable"]);
      expect(source(health, "openfda")).toMatchObject({
        problems: ["contract_unchecked"],
        contract: { status: "unchecked", checkedAt: null, error: null },
      });
    }));

  it("treats a passing probe older than 36 hours as stale", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      await setSource(tx, "openfda", { contractCheckedAt: HOURS_AGO(40) });
      expect(source(await getHealth(tx, NOW), "openfda").problems).toEqual(["contract_stale"]);
    }));

  it("flags RASFF when no new Notification arrived in 7 days", () =>
    withRollback(async (tx) => {
      for (const code of ["rasff", "nvwa", "openfda"]) await setSource(tx, code);
      await seen(tx, 1, "2026.9000", HOURS_AGO(7 * 24 + 1));
      const health = await getHealth(tx, NOW);
      expect(source(health, "rasff")).toMatchObject({
        ok: false,
        problems: ["silent"],
        silent: true,
        newNotifications: { count: 0, lastFirstSeenAt: "2026-10-18T11:00:00.000Z" },
      });
      // Only RASFF publishes daily; quiet weeks are normal for NVWA and openFDA.
      expect(source(health, "nvwa")).toMatchObject({
        ok: true,
        silent: false,
        newNotifications: { count: 0, lastFirstSeenAt: null },
      });
      expect(health.status).toBe("degraded");
    }));

  it("lists several problems of one Source", () =>
    withRollback(async (tx) => {
      await setSource(tx, "rasff", { lastSuccessAt: null, contractStatus: "failed" });
      expect(source(await getHealth(tx, NOW), "rasff").problems).toEqual([
        "never_succeeded",
        "contract_failed",
        "silent",
      ]);
    }));

  it("never exposes the text of the last job error", () =>
    withRollback(async (tx) => {
      await healthy(tx);
      await setSource(tx, "openfda", {
        lastErrorAt: HOURS_AGO(1),
        lastError: "HTTPStatusError: Client error for url ...&api_key=SECRET",
      });
      expect(JSON.stringify(await getHealth(tx, NOW))).not.toContain("SECRET");
    }));
});

describe("getHealth as ofa_web", () => {
  it("reads every column it needs with the read-only web role", async () => {
    const url = new URL(TEST_URL);
    url.username = "ofa_web";
    url.password = process.env.OFA_WEB_PASSWORD ?? "ofa_web_local";
    const web = postgres(url.toString(), { max: 1, onnotice: () => {} });
    try {
      const health = await getHealth(drizzle(web), NOW);
      expect(health.sources).toHaveLength(3);
    } finally {
      await web.end();
    }
  });
});
