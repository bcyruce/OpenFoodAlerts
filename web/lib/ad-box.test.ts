import { describe, expect, it } from "vitest";
import { isAdBoxAllowed } from "./ad-box";

// Spec §11.3 rule 3: the SnelVink ad box appears only at the bottom of the home page and
// on /zh/* pages; never on the dashboard, search, detail, evaluation or data pages.
describe("isAdBoxAllowed", () => {
  it("allows the home page in en and nl", () => {
    expect(isAdBoxAllowed("/en")).toBe(true);
    expect(isAdBoxAllowed("/nl")).toBe(true);
    expect(isAdBoxAllowed("/nl/")).toBe(true);
  });

  it("allows the pages of the Chinese module", () => {
    expect(isAdBoxAllowed("/zh")).toBe(true);
    expect(isAdBoxAllowed("/zh/nvwa-jiancha")).toBe(true);
    expect(isAdBoxAllowed("/zh/jinggao")).toBe(true);
  });

  it.each([
    "/en/dashboard",
    "/nl/dashboard",
    "/en/search",
    "/en/n/openfda/H-0015-2027",
    "/nl/n/nvwa/actueel/nieuws/2026/10/24/x",
    "/en/evaluation",
    "/en/data",
    "/en/about",
    "/nl/privacy",
    "/en/disclaimer",
    "/en/colofon",
    "/en/alerts",
    "/nl/alerts/manage/abc",
  ])("refuses %s", (path) => {
    expect(isAdBoxAllowed(path)).toBe(false);
  });

  it("keeps it off the zh subscription flow and the zh legal and data pages", () => {
    for (const path of [
      "/zh/alerts",
      "/zh/alerts/confirm",
      "/zh/alerts/manage/abc",
      "/zh/about",
      "/zh/privacy",
      "/zh/disclaimer",
      "/zh/colofon",
      "/zh/data",
      "/zh/dashboard",
      "/zh/search",
      "/zh/n/nvwa/x",
      "/zh/evaluation",
    ]) {
      expect(isAdBoxAllowed(path), path).toBe(false);
    }
  });

  it("refuses unknown locales and paths without a locale", () => {
    expect(isAdBoxAllowed("/")).toBe(false);
    expect(isAdBoxAllowed("/fr")).toBe(false);
    expect(isAdBoxAllowed("")).toBe(false);
  });
});
