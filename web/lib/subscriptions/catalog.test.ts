// Against the seeded TEST_DATABASE_URL (`make test-db` loads db/seed/rasff).
import { afterAll, describe, expect, it } from "vitest";
import { testClient, withRollback } from "@/lib/test-db";
import { getFilterCatalog, knownFilterValues, localizeCatalog } from "./catalog";

afterAll(() => testClient.end());

describe("filter catalog", () => {
  it("lists the seeded categories by RASFF id and only real countries", () =>
    withRollback(async (tx) => {
      const catalog = await getFilterCatalog(tx);
      const known = knownFilterValues(catalog);
      expect(known.hazardCategories).toContain(21798);
      expect(known.hazardCategories).toHaveLength(30);
      expect(known.productCategories).toHaveLength(37);
      expect(known.countries).toEqual(expect.arrayContaining(["NL", "CN", "XI"]));
      expect(known.countries).not.toContain("ECDC");
    }, { role: "ofa_web" }));

  it("labels countries in the page language, falling back to the RASFF name", () =>
    withRollback(async (tx) => {
      const catalog = await getFilterCatalog(tx);
      const label = (locale: "en" | "nl" | "zh", iso2: string) =>
        localizeCatalog(catalog, locale).countries.find((c) => c.value === iso2)?.label;
      expect(label("en", "NL")).toBe("Netherlands");
      expect(label("nl", "NL")).toBe("Nederland");
      expect(label("zh", "NL")).toBe("荷兰");
      expect(label("nl", "XI")).toBe("United Kingdom (Northern Ireland)");
    }));
});
