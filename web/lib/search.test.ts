// Integration tests against TEST_DATABASE_URL (migrated by `make test-db`, seeds loaded).
// Each test deletes all Notifications and inserts its own inside a transaction that is
// rolled back, so neither leftovers from pipeline tests nor these rows leak.
import { afterAll, describe, expect, it } from "vitest";
import { NO_FILTERS, type Filters, type SearchQuery } from "./filters";
import { searchNotifications } from "./search";
import { testClient } from "./test-db";
import {
  ALLERGENS,
  HERBS,
  MILK_PRODUCTS,
  PATHOGENS,
  PESTICIDES,
  withNotifications,
  type Row,
} from "./test-notifications";

afterAll(() => testClient.end());

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

  it("says who made each AI value, and a person's review, for the badge", () =>
    withNotifications(
      [
        {
          ...MILK_NVWA,
          ai: [
            {
              task: "hazard_category",
              value: { category: "allergens" },
              model: "fake",
              promptVersion: "v1",
              createdAt: "2026-10-24T10:00:00Z",
              derived: { hazardCategory: ALLERGENS },
            },
            {
              task: "origin_country",
              value: { country: "DE" },
              reviewStatus: "corrected",
              reviewedValue: { country: "BE" },
              derived: { originCountry: "BE" },
            },
          ],
        },
      ],
      async (tx) => {
        const r = await searchNotifications(tx, query(""), { locale: "en" });
        const [result] = r.results;
        expect(result.sourceUrl).toBe(`https://example.test/${MILK_NVWA.key}`);
        expect(result.hazardCategories).toEqual([
          {
            value: String(ALLERGENS),
            label: "allergens",
            provenance: "ai",
            ai: {
              classificationId: expect.any(Number),
              task: "hazard_category",
              model: "fake",
              promptVersion: "v1",
              createdAt: "2026-10-24T10:00:00.000Z",
              reviewed: false,
            },
          },
        ]);
        expect(result.originCountries).toMatchObject([
          { value: "BE", provenance: "ai", ai: { task: "origin_country", reviewed: true } },
        ]);
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
