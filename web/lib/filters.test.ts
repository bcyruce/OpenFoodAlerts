import { describe, expect, it } from "vitest";
import { NO_FILTERS, parseFilters, parseSearchQuery, toSearchParams } from "./filters";

describe("parseFilters", () => {
  it("reads the spec §8 array parameters, with or without []", () => {
    const params = new URLSearchParams(
      "source[]=rasff&source=nvwa&hazard[]=21798&product=18454&country[]=TR&risk=serious&risk[]=not_graded",
    );
    expect(parseFilters(params)).toEqual({
      sources: ["nvwa", "rasff"],
      hazardCategories: [21798],
      productCategories: [18454],
      countries: ["TR"],
      risks: ["not_graded", "serious"],
      from: null,
      to: null,
      officialOnly: false,
    });
  });

  it("accepts a Next.js searchParams object", () => {
    expect(
      parseFilters({ source: ["openfda", "rasff"], country: "nl", official_only: "1" }),
    ).toMatchObject({ sources: ["openfda", "rasff"], countries: ["NL"], officialOnly: true });
  });

  it("drops values it cannot use instead of failing", () => {
    const params = new URLSearchParams(
      "source=xyz&hazard=abc&hazard=-3&product=1.5&country=n1&from=2026-13-01&to=yesterday&official_only=maybe",
    );
    expect(parseFilters(params)).toEqual(NO_FILTERS);
  });

  it("removes duplicates", () => {
    const params = new URLSearchParams("hazard=2&hazard=1&hazard=2&source=rasff&source=rasff");
    expect(parseFilters(params)).toMatchObject({ hazardCategories: [1, 2], sources: ["rasff"] });
  });

  it("reads dates as calendar days and puts them in order", () => {
    expect(parseFilters(new URLSearchParams("from=2026-10-31&to=2026-01-01"))).toMatchObject({
      from: "2026-01-01",
      to: "2026-10-31",
    });
    expect(parseFilters(new URLSearchParams("to=2026-02-29"))).toMatchObject({ to: null });
  });

  it("treats true, on and 1 as switching official_only on", () => {
    for (const value of ["true", "on", "1"]) {
      expect(parseFilters({ official_only: value }).officialOnly).toBe(true);
    }
    expect(parseFilters({ official_only: "0" }).officialOnly).toBe(false);
  });
});

describe("parseSearchQuery", () => {
  it("adds the text query and the page to the filters", () => {
    const query = parseSearchQuery(new URLSearchParams("q=+ethylene%20oxide+&page=3&source=rasff"));
    expect(query).toMatchObject({ q: "ethylene oxide", page: 3, filters: { sources: ["rasff"] } });
  });

  it("starts at page 1 and keeps the page within bounds", () => {
    expect(parseSearchQuery({}).page).toBe(1);
    expect(parseSearchQuery({ page: "0" }).page).toBe(1);
    expect(parseSearchQuery({ page: "two" }).page).toBe(1);
    expect(parseSearchQuery({ page: "100000" }).page).toBe(500);
  });

  it("limits the text query to 200 characters", () => {
    expect(parseSearchQuery({ q: "a".repeat(300) }).q).toHaveLength(200);
  });
});

describe("toSearchParams", () => {
  it("writes the canonical URL form that parseSearchQuery reads back", () => {
    const query = {
      q: "salmonella",
      page: 2,
      filters: {
        ...NO_FILTERS,
        sources: ["rasff" as const, "nvwa" as const],
        hazardCategories: [21798],
        countries: ["TR"],
        from: "2026-01-01",
        officialOnly: true,
      },
    };
    const params = toSearchParams(query);
    expect(params.toString()).toBe(
      "q=salmonella&source=rasff&source=nvwa&hazard=21798&country=TR&from=2026-01-01&official_only=1&page=2",
    );
    expect(parseSearchQuery(params)).toEqual({
      ...query,
      filters: { ...query.filters, sources: ["nvwa", "rasff"] },
    });
  });

  it("leaves out empty parameters and page 1", () => {
    expect(toSearchParams({ q: "", page: 1, filters: NO_FILTERS }).toString()).toBe("");
  });
});
