import { describe, expect, it } from "vitest";
import { NO_FILTERS } from "./filters";
import { parseStatsQuery, resolvePeriod, toStatsParams } from "./stats-query";

const params = (s: string) => new URLSearchParams(s);

describe("parseStatsQuery", () => {
  it("defaults to the last 12 months", () => {
    expect(parseStatsQuery(params(""))).toEqual({ filters: NO_FILTERS, months: 12 });
  });

  it("expresses S1: herbs and spices over the last 12 months", () => {
    const q = parseStatsQuery(params("product=18450&months=12"));
    expect(q).toEqual({ filters: { ...NO_FILTERS, productCategories: [18450] }, months: 12 });
    // The default period is left out of the canonical URL.
    expect(toStatsParams(q).toString()).toBe("product=18450");
  });

  it("takes other periods, all time, and gives from/to precedence", () => {
    expect(parseStatsQuery(params("months=24")).months).toBe(24);
    expect(parseStatsQuery(params("months=all")).months).toBeNull();
    expect(parseStatsQuery(params("months=9999")).months).toBe(240);
    expect(parseStatsQuery(params("months=0")).months).toBe(12);
    expect(parseStatsQuery(params("months=soon")).months).toBe(12);
    expect(parseStatsQuery(params("from=2026-01-01&months=3"))).toEqual({
      filters: { ...NO_FILTERS, from: "2026-01-01" },
      months: null,
    });
  });

  it("reads a page's searchParams object as well", () => {
    expect(parseStatsQuery({ "source[]": ["nvwa", "rasff"], months: "6" })).toEqual({
      filters: { ...NO_FILTERS, sources: ["nvwa", "rasff"] },
      months: 6,
    });
  });
});

describe("toStatsParams", () => {
  it("round-trips through the canonical URL form", () => {
    for (const s of [
      "",
      "source=nvwa&source=rasff&official_only=1&months=all",
      "hazard=21798&country=IN&months=24",
      "from=2026-01-01&to=2026-06-30",
    ]) {
      expect(toStatsParams(parseStatsQuery(params(s))).toString()).toBe(s);
    }
  });
});

describe("resolvePeriod", () => {
  it("starts on the first day of the month N − 1 months back, in Amsterdam", () => {
    const q = { filters: NO_FILTERS, months: 12 };
    expect(resolvePeriod(q, new Date("2026-10-25T12:00:00Z")).from).toBe("2025-11-01");
    // 31 December 23:30 UTC is already January in Amsterdam.
    expect(resolvePeriod({ ...q, months: 1 }, new Date("2026-12-31T23:30:00Z")).from).toBe(
      "2027-01-01",
    );
    expect(resolvePeriod({ ...q, months: 3 }, new Date("2026-02-10T12:00:00Z")).from).toBe(
      "2025-12-01",
    );
  });

  it("leaves explicit dates and all time alone", () => {
    const filters = { ...NO_FILTERS, from: "2026-01-01" };
    expect(resolvePeriod({ filters, months: null }, new Date())).toBe(filters);
  });
});
