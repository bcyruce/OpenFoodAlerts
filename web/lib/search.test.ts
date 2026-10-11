// Integration tests against TEST_DATABASE_URL (migrated by `make test-db`, seeds loaded).
// Each test deletes all Notifications and inserts its own inside a transaction that is
// rolled back, so neither leftovers from pipeline tests nor these rows leak.
import { sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { afterAll, describe, expect, it } from "vitest";
import { NO_FILTERS, type Filters, type SearchQuery } from "./filters";
import { searchNotifications } from "./search";

const client = postgres(
  process.env.TEST_DATABASE_URL ?? "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable",
  { max: 1, onnotice: () => {} },
);
const db = drizzle(client);

afterAll(() => client.end());

type Tx = Parameters<Parameters<typeof db.transaction>[0]>[0];

class Rollback extends Error {}

async function withNotifications(
  rows: Row[],
  fn: (tx: Tx) => Promise<void>,
): Promise<void> {
  try {
    await db.transaction(async (tx) => {
      await tx.execute(sql`DELETE FROM notifications`);
      for (const row of rows) await insert(tx, row);
      await fn(tx);
      throw new Rollback();
    });
  } catch (e) {
    if (!(e instanceof Rollback)) throw e;
  }
}

const SOURCE_IDS = { rasff: 1, nvwa: 2, openfda: 3 } as const;

// Seeded RASFF dictionary ids.
const ALLERGENS = 21798;
const PATHOGENS = 21801;
const PESTICIDES = 21795;
const MILK_PRODUCTS = 18454; // "milk and milk products"
const HERBS = 18450; // "herbs and spices"

type Row = {
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

/** One Notification as the pipeline writes it, search_tsv included. */
async function insert(tx: Tx, r: Row): Promise<void> {
  const sid = SOURCE_IDS[r.source];
  const [raw] = await tx.execute<{ id: number }>(sql`
    INSERT INTO raw_records (source_id, source_key, kind, url, http_status, content_hash, content_type, body)
    VALUES (${sid}, ${r.key}, 'detail', 'https://example.test', 200, 'x', 'application/json', '\\x7b7d')
    RETURNING id`);
  const productType = r.productType === undefined ? "food" : r.productType;
  const provenance =
    r.productTypeProvenance ?? (productType === null ? "pending" : r.source === "rasff" ? "official" : "rule");
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

function query(q: string, filters: Partial<Filters> = {}, page = 1): SearchQuery {
  return { q, page, filters: { ...NO_FILTERS, ...filters } };
}

const keys = (r: { results: { sourceKey: string }[] }) => r.results.map((x) => x.sourceKey);

const EO_RASFF: Row = {
  source: "rasff",
  key: "2026.0001",
  title: "Ethylene oxide in sesame seeds from India",
  publishedAt: "2026-10-20T08:00:00Z",
  risk: "serious",
  productText: "sesame seeds",
  hazardText: "ethylene oxide",
  hazards: [{ name: "ethylene oxide", category: PESTICIDES }],
  productCategories: [{ category: HERBS }],
  countries: [{ iso2: "IN" }, { iso2: "NL", role: "notifying" }],
};
const EO_FDA: Row = {
  source: "openfda",
  key: "H-0001-2027",
  title: "SESAME TAHINI",
  publishedAt: "2026-10-10T04:00:00Z",
  risk: "Class II",
  productText: "SESAME TAHINI 500 g jar",
  hazardText: "Contains ethylene oxide above the tolerance",
};
const EO_NEWS: Row = {
  source: "rasff",
  key: "2026.0002",
  title: "News: ethylene oxide in locust bean gum",
  publishedAt: "2026-09-01T08:00:00Z",
  notificationType: "news",
};
const MILK_NVWA: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/05/veiligheidswaarschuwing-pindakaas",
  title: "Veiligheidswaarschuwing pindakaas met melk",
  publishedAt: "2026-10-05T09:00:00Z",
  productText: "Pindakaas 350 gram",
};
const SALMONELLA_RASFF: Row = {
  source: "rasff",
  key: "2026.0003",
  title: "Salmonella in raw milk cheese from France",
  publishedAt: "2026-08-15T08:00:00Z",
  risk: "potentially serious",
  hazards: [{ name: "Salmonella", category: PATHOGENS }],
  productCategories: [{ category: MILK_PRODUCTS }],
  countries: [{ iso2: "FR" }],
};
const NON_FOOD: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/06/veiligheidswaarschuwing-powerbank",
  title: "Veiligheidswaarschuwing powerbank met ethylene oxide",
  productType: "non-food",
};
const PENDING: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/07/veiligheidswaarschuwing-pan",
  title: "Veiligheidswaarschuwing pan ethylene oxide",
  productType: null,
};

const ALL = [EO_RASFF, EO_FDA, EO_NEWS, MILK_NVWA, SALMONELLA_RASFF, NON_FOOD, PENDING];

describe("searchNotifications", () => {
  it("finds matching Notifications from every Source, newest first, within the display scope", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query("ethylene oxide"), { locale: "en" });
      // non-food and pending are never shown; RASFF News is searchable (spec §4.3).
      expect(keys(r)).toEqual(["2026.0001", "H-0001-2027", "2026.0002"]);
      expect(r.total).toBe(3);
      expect(r.page).toBe(1);
      expect(r.pageCount).toBe(1);
      expect(r.results[0]).toMatchObject({
        source: "rasff",
        title: "Ethylene oxide in sesame seeds from India",
        path: "/en/n/rasff/2026.0001",
        publishedAt: "2026-10-20T08:00:00.000Z",
        notificationType: "alert notification",
        riskOfficial: "serious",
        productType: "food",
        hazardText: "ethylene oxide",
        hazardCategories: [{ value: "21795", label: "pesticide residues", provenance: "official" }],
        productCategories: [{ value: String(HERBS), label: "herbs and spices", provenance: "official" }],
        originCountries: [{ value: "IN", label: "India", provenance: "official" }],
      });
    }));

  it("lists everything shown when there is no text query", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query(""), { locale: "en" });
      expect(r.total).toBe(5);
    }));

  it("finds partial words in the product text", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query("tahin"), { locale: "en" });
      expect(keys(r)).toEqual(["H-0001-2027"]);
    }));

  it("filters by Source and counts each Source as if its own filter were not set", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query("ethylene oxide", { sources: ["openfda"] }), {
        locale: "en",
      });
      expect(keys(r)).toEqual(["H-0001-2027"]);
      expect(r.facets.source).toEqual([
        { value: "rasff", label: "RASFF", count: 2, selected: false },
        { value: "openfda", label: "openFDA", count: 1, selected: true },
      ]);
    }));

  it("filters by Hazard category, Product category, origin country and date", () =>
    withNotifications(ALL, async (tx) => {
      const search = (f: Partial<Filters>) =>
        searchNotifications(tx, query("", f), { locale: "en" }).then(keys);
      expect(await search({ hazardCategories: [PATHOGENS] })).toEqual(["2026.0003"]);
      expect(await search({ productCategories: [HERBS, MILK_PRODUCTS] })).toEqual([
        "2026.0001",
        "2026.0003",
      ]);
      // Only the origin role counts: NL is the notifying country of 2026.0001.
      expect(await search({ countries: ["NL"] })).toEqual([]);
      expect(await search({ countries: ["FR", "IN"] })).toEqual(["2026.0001", "2026.0003"]);
      // Calendar days in Europe/Amsterdam, both ends inclusive.
      expect(await search({ from: "2026-10-05", to: "2026-10-10" })).toEqual([
        "H-0001-2027",
        "/actueel/nieuws/2026/10/05/veiligheidswaarschuwing-pindakaas",
      ]);
    }));

  it("filters by official severity, with NOT_GRADED for Sources that do not grade", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query("", { risks: ["not_graded", "Class II"] }), {
        locale: "en",
      });
      expect(keys(r)).toEqual([
        "H-0001-2027",
        "/actueel/nieuws/2026/10/05/veiligheidswaarschuwing-pindakaas",
        "2026.0002",
      ]);
      expect(r.facets.risk).toContainEqual({
        value: "not_graded",
        label: "Not graded",
        count: 2,
        selected: true,
      });
      expect(r.facets.risk).toContainEqual({
        value: "serious",
        label: "serious",
        count: 1,
        selected: false,
      });
    }));

  it("counts Hazard categories, Product categories and origin countries", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query(""), { locale: "en" });
      expect(r.facets.hazard).toEqual([
        { value: String(PATHOGENS), label: "pathogenic micro-organisms", count: 1, selected: false },
        { value: String(PESTICIDES), label: "pesticide residues", count: 1, selected: false },
      ]);
      expect(r.facets.product.map((f) => f.label)).toEqual(["herbs and spices", "milk and milk products"]);
      expect(r.facets.country.map((f) => [f.value, f.count])).toEqual([
        ["FR", 1],
        ["IN", 1],
      ]);
    }));

  it("keeps selected values in the facets even when nothing matches them", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query("", { hazardCategories: [ALLERGENS] }), {
        locale: "en",
      });
      expect(r.total).toBe(0);
      expect(r.facets.hazard).toContainEqual({
        value: String(ALLERGENS),
        label: "allergens",
        count: 0,
        selected: true,
      });
    }));

  it("uses AI classifications unless official_only is on", () =>
    withNotifications(
      [
        ...ALL,
        {
          ...MILK_NVWA,
          key: "/actueel/nieuws/2026/10/08/veiligheidswaarschuwing-koekjes",
          title: "Veiligheidswaarschuwing koekjes",
          hazards: [{ name: "melk", category: ALLERGENS, provenance: "ai" }],
          countries: [{ iso2: "BE", provenance: "ai" }],
        },
      ],
      async (tx) => {
        const withAi = await searchNotifications(tx, query("", { hazardCategories: [ALLERGENS] }), {
          locale: "en",
        });
        expect(withAi.total).toBe(1);
        expect(withAi.results[0].hazardCategories).toEqual([
          { value: String(ALLERGENS), label: "allergens", provenance: "ai" },
        ]);
        const official = await searchNotifications(
          tx,
          query("", { hazardCategories: [ALLERGENS], officialOnly: true }),
          { locale: "en" },
        );
        expect(official.total).toBe(0);
        const all = await searchNotifications(tx, query("koekjes", { officialOnly: true }), {
          locale: "en",
        });
        expect(all.results[0].hazardCategories).toEqual([]);
        expect(all.results[0].originCountries).toEqual([]);
        expect(all.facets.country).toEqual([]);
      },
    ));

  it("pages through the results", () =>
    withNotifications(ALL, async (tx) => {
      const page2 = await searchNotifications(tx, query("", {}, 2), { locale: "en", pageSize: 2 });
      expect(page2.total).toBe(5);
      expect(page2.pageCount).toBe(3);
      expect(keys(page2)).toEqual([
        "/actueel/nieuws/2026/10/05/veiligheidswaarschuwing-pindakaas",
        "2026.0002",
      ]);
    }));

  it("labels countries in the visitor's language", () =>
    withNotifications(ALL, async (tx) => {
      const r = await searchNotifications(tx, query(""), { locale: "nl" });
      expect(r.facets.country.map((f) => f.label)).toEqual(["Frankrijk", "India"]);
      expect(r.results[0].path).toBe("/nl/n/rasff/2026.0001");
    }));
});
