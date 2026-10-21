// Integration tests for the dashboard statistics against TEST_DATABASE_URL (migrated and
// seeded by `make test-db`). Each test replaces all Notifications inside a rolled-back
// transaction. Expected numbers are counted by hand from the rows below.
import { afterAll, describe, expect, it } from "vitest";
import { NO_FILTERS, type Filters } from "./filters";
import { getStats, type SourceStats, type StatsResponse } from "./stats";
import type { StatsQuery } from "./stats-query";
import { testClient } from "./test-db";
import {
  HERBS,
  MILK_PRODUCTS,
  PATHOGENS,
  PESTICIDES,
  withNotifications,
  type Row,
} from "./test-notifications";

afterAll(() => testClient.end());

// "Now" for the default period: 25 October 2026, Amsterdam.
const NOW = new Date("2026-10-25T12:00:00Z");

function query(filters: Partial<Filters> = {}, months: number | null = null): StatsQuery {
  return { filters: { ...NO_FILTERS, ...filters }, months };
}

function source(r: StatsResponse, code: string): SourceStats {
  const s = r.sources.find((x) => x.source === code);
  if (!s) throw new Error(`no stats for ${code}`);
  return s;
}

const SESAME_IN: Row = {
  source: "rasff",
  key: "2026.0001",
  title: "Ethylene oxide in sesame seeds from India",
  publishedAt: "2026-10-20T08:00:00Z",
  hazards: [{ name: "ethylene oxide", category: PESTICIDES }],
  productCategories: [{ category: HERBS }],
  countries: [{ iso2: "IN" }, { iso2: "NL", role: "notifying" }],
};
const CHILLI_IN: Row = {
  source: "rasff",
  key: "2026.0002",
  title: "Salmonella and chlorpyrifos in chilli powder from India",
  publishedAt: "2026-10-03T08:00:00Z",
  hazards: [
    { name: "Salmonella", category: PATHOGENS },
    { name: "chlorpyrifos", category: PESTICIDES },
    { name: "ethylene oxide", category: PESTICIDES },
  ],
  productCategories: [{ category: HERBS }],
  countries: [{ iso2: "IN" }],
};
const PEPPER_BR: Row = {
  source: "rasff",
  key: "2026.0003",
  title: "Salmonella in black pepper from Brazil",
  // 31 August 23:30 UTC is 1 September in Amsterdam.
  publishedAt: "2026-08-31T23:30:00Z",
  hazards: [{ name: "Salmonella", category: PATHOGENS }],
  productCategories: [{ category: HERBS }],
  countries: [{ iso2: "BR" }],
};
const CHEESE_FR: Row = {
  source: "rasff",
  key: "2026.0004",
  title: "Listeria in cheese from France",
  publishedAt: "2026-09-10T08:00:00Z",
  hazards: [{ name: "Listeria", category: PATHOGENS }],
  productCategories: [{ category: MILK_PRODUCTS }],
  countries: [{ iso2: "FR" }],
};
const OLD_RASFF: Row = {
  source: "rasff",
  key: "2024.0001",
  title: "Aflatoxins in nutmeg from Indonesia",
  publishedAt: "2024-03-01T08:00:00Z",
  hazards: [{ name: "aflatoxins", category: PESTICIDES }],
  productCategories: [{ category: HERBS }],
  countries: [{ iso2: "ID" }],
};
const NEWS: Row = {
  source: "rasff",
  key: "2026.0005",
  title: "News: ethylene oxide",
  publishedAt: "2026-10-01T08:00:00Z",
  notificationType: "news",
  hazards: [{ name: "ethylene oxide", category: PESTICIDES }],
  countries: [{ iso2: "IN" }],
};
const FCM: Row = {
  source: "rasff",
  key: "2026.0006",
  title: "Migration of formaldehyde from melamine plates",
  publishedAt: "2026-10-02T08:00:00Z",
  productType: "food contact material",
  countries: [{ iso2: "CN" }],
};
const NVWA_MILK: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/05/veiligheidswaarschuwing-pindakaas",
  title: "Veiligheidswaarschuwing pindakaas met melk",
  publishedAt: "2026-10-05T09:00:00Z",
};
const NVWA_SPICE_AI: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/13/veiligheidswaarschuwing-korianderzaad",
  title: "Veiligheidswaarschuwing korianderzaad",
  publishedAt: "2026-10-13T09:00:00Z",
  hazards: [{ name: "salmonella", category: PATHOGENS, provenance: "ai" }],
  productCategories: [{ category: HERBS, provenance: "ai" }],
  countries: [{ iso2: "IN", provenance: "ai" }],
};
const NVWA_NON_FOOD: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/06/veiligheidswaarschuwing-powerbank",
  title: "Veiligheidswaarschuwing powerbank",
  publishedAt: "2026-10-06T09:00:00Z",
  productType: "non-food",
};
const NVWA_PENDING: Row = {
  source: "nvwa",
  key: "/actueel/nieuws/2026/10/07/veiligheidswaarschuwing-pan",
  title: "Veiligheidswaarschuwing pan",
  publishedAt: "2026-10-07T09:00:00Z",
  productType: null,
};
// The same incident as SESAME_IN, published by another Source: counted again (ADR 0005).
const FDA_SESAME: Row = {
  source: "openfda",
  key: "H-0001-2027",
  title: "SESAME SEEDS",
  publishedAt: "2026-10-21T04:00:00Z",
  risk: "Class II",
};

const ALL = [
  SESAME_IN,
  CHILLI_IN,
  PEPPER_BR,
  CHEESE_FR,
  OLD_RASFF,
  NEWS,
  FCM,
  NVWA_MILK,
  NVWA_SPICE_AI,
  NVWA_NON_FOOD,
  NVWA_PENDING,
  FDA_SESAME,
];

describe("getStats", () => {
  it("counts each Source separately within the statistics scope", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query(), { locale: "en", now: NOW });
      // All three Sources, always in the same order, never summed or deduplicated.
      expect(r.sources.map((s) => [s.source, s.label, s.total])).toEqual([
        // RASFF News, non-food and pending are left out (spec §4.3); FCM counts.
        ["rasff", "RASFF", 6],
        ["nvwa", "NVWA", 2],
        ["openfda", "openFDA", 1],
      ]);
    }));

  it("counts per Amsterdam calendar month over the last 12 months by default", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query({}, 12), { locale: "en", now: NOW });
      expect(r.period).toEqual({ months: 12, from: "2025-11-01", to: null });
      expect(r.months).toEqual([
        "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04",
        "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10",
      ]);
      // OLD_RASFF (2024) is outside the period; PEPPER_BR falls in September.
      expect(source(r, "rasff").total).toBe(5);
      expect(source(r, "rasff").monthly).toEqual([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 3]);
      expect(source(r, "nvwa").monthly.slice(-2)).toEqual([0, 2]);
      expect(source(r, "openfda").monthly.slice(-1)).toEqual([1]);
    }));

  it("spans all months with data, up to the current month, without a lower bound", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query(), { locale: "en", now: NOW });
      expect(r.period).toEqual({ months: null, from: null, to: null });
      expect(r.months[0]).toBe("2024-03");
      expect(r.months.at(-1)).toBe("2026-10");
      expect(r.months).toHaveLength(32);
      expect(source(r, "rasff").monthly[0]).toBe(1);
    }));

  it("covers exactly the months between from and to", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query({ from: "2026-09-01", to: "2026-09-30" }), {
        locale: "en",
        now: NOW,
      });
      expect(r.months).toEqual(["2026-09"]);
      expect(source(r, "rasff").monthly).toEqual([2]);
      expect(source(r, "nvwa").monthly).toEqual([0]);
    }));

  it("ranks Hazard categories, Product categories and origin countries per Source", () =>
    withNotifications(ALL, async (tx) => {
      const rasff = source(await getStats(tx, query(), { locale: "en", now: NOW }), "rasff");
      // CHILLI_IN has two pesticide hazards and counts once for that category.
      expect(rasff.top.hazard).toEqual([
        { value: String(PATHOGENS), label: "pathogenic micro-organisms", count: 3, ai: 0 },
        { value: String(PESTICIDES), label: "pesticide residues", count: 3, ai: 0 },
      ]);
      expect(rasff.top.product).toEqual([
        { value: String(HERBS), label: "herbs and spices", count: 4, ai: 0 },
        { value: String(MILK_PRODUCTS), label: "milk and milk products", count: 1, ai: 0 },
      ]);
      // Origin only: NL is a notifying country.
      expect(rasff.top.country).toEqual([
        { value: "IN", label: "India", count: 2, ai: 0 },
        { value: "BR", label: "Brazil", count: 1, ai: 0 },
        { value: "CN", label: "China", count: 1, ai: 0 },
        { value: "FR", label: "France", count: 1, ai: 0 },
        { value: "ID", label: "Indonesia", count: 1, ai: 0 },
      ]);
      // FCM has no Hazard or Product category.
      expect(rasff.classified).toEqual({ hazard: 5, product: 5, country: 6 });
    }));

  it("uses AI classifications unless official_only is on", () =>
    withNotifications(ALL, async (tx) => {
      const withAi = source(await getStats(tx, query(), { locale: "en", now: NOW }), "nvwa");
      expect(withAi.top.hazard).toEqual([
        { value: String(PATHOGENS), label: "pathogenic micro-organisms", count: 1, ai: 1 },
      ]);
      expect(withAi.classified).toEqual({ hazard: 1, product: 1, country: 1 });
      const official = source(
        await getStats(tx, query({ officialOnly: true }), { locale: "en", now: NOW }),
        "nvwa",
      );
      // The Notifications still count; their AI classifications do not.
      expect(official.total).toBe(2);
      expect(official.top).toEqual({ hazard: [], product: [], country: [] });
      expect(official.classified).toEqual({ hazard: 0, product: 0, country: 0 });
      const filtered = await getStats(
        tx,
        query({ productCategories: [HERBS], officialOnly: true }),
        { locale: "en", now: NOW },
      );
      expect(source(filtered, "nvwa").total).toBe(0);
      expect(source(filtered, "rasff").total).toBe(4);
    }));

  it("says how many Notifications each value counts through an AI classification", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query(), { locale: "en", now: NOW });
      const nvwa = source(r, "nvwa");
      expect(nvwa.top.product).toEqual([
        { value: String(HERBS), label: "herbs and spices", count: 1, ai: 1 },
      ]);
      expect(nvwa.classifiedAi).toEqual({ hazard: 1, product: 1, country: 1 });
      const rasff = source(r, "rasff");
      expect(rasff.top.product[0]).toEqual({
        value: String(HERBS),
        label: "herbs and spices",
        count: 4,
        ai: 0,
      });
      expect(rasff.classifiedAi).toEqual({ hazard: 0, product: 0, country: 0 });
    }));

  it("counts Hazard category × origin country pairs per month for the heatmap", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query({}, 12), { locale: "en", now: NOW });
      const z = (tail: number[]) => [...Array(12 - tail.length).fill(0), ...tail];
      expect(source(r, "rasff").heatmap).toEqual([
        {
          hazard: { value: String(PESTICIDES), label: "pesticide residues" },
          country: { value: "IN", label: "India" },
          total: 2,
          counts: z([0, 2]),
        },
        {
          hazard: { value: String(PATHOGENS), label: "pathogenic micro-organisms" },
          country: { value: "BR", label: "Brazil" },
          total: 1,
          counts: z([1, 0]),
        },
        {
          hazard: { value: String(PATHOGENS), label: "pathogenic micro-organisms" },
          country: { value: "FR", label: "France" },
          total: 1,
          counts: z([1, 0]),
        },
        {
          hazard: { value: String(PATHOGENS), label: "pathogenic micro-organisms" },
          country: { value: "IN", label: "India" },
          total: 1,
          counts: z([0, 1]),
        },
      ]);
      expect(source(r, "openfda").heatmap).toEqual([]);
    }));

  it("labels countries in the visitor's language", () =>
    withNotifications(ALL, async (tx) => {
      const r = await getStats(tx, query(), { locale: "nl", now: NOW });
      expect(source(r, "rasff").top.country.map((c) => c.label)).toEqual([
        "India",
        "Brazilië",
        "China",
        "Frankrijk",
        "Indonesië",
      ]);
    }));
});
