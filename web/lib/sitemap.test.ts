import { describe, expect, it } from "vitest";
import { buildSitemap, zhSitemapPages } from "./sitemap";

const SITE = "https://openfoodalerts.nl";

describe("buildSitemap", () => {
  const entries = buildSitemap(SITE, [
    {
      source: "nvwa",
      key: "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-kaas",
      lastChangedAt: "2026-10-24T10:00:00.000Z",
    },
  ], [
    { path: "/zh", reviewedOn: "2026-10-20" },
    { path: "/zh/jinkou", reviewedOn: null },
  ]);
  const byUrl = new Map(entries.map((e) => [e.url, e]));

  it("lists the reviewed Chinese module pages in zh only, with their review date", () => {
    expect(byUrl.get(`${SITE}/zh`)).toEqual({ url: `${SITE}/zh`, lastModified: "2026-10-20" });
    // Drafts are noindex until the owner has reviewed them.
    expect(byUrl.has(`${SITE}/zh/jinkou`)).toBe(false);
  });

  it("takes the Chinese module pages from content/zh by default", () => {
    const urls = buildSitemap(SITE, []).map((e) => e.url);
    expect(urls.filter((u) => u.startsWith(`${SITE}/zh`) && !/(about|privacy|disclaimer|colofon)$/.test(u)))
      .toEqual(
        zhSitemapPages()
          .filter((p) => p.reviewedOn !== null)
          .map((p) => `${SITE}${p.path}`),
      );
    expect(zhSitemapPages().map((p) => p.path)).toEqual([
      "/zh",
      "/zh/nvwa-jiancha",
      "/zh/zhaohui-jinggao",
      "/zh/jiancha-jieguo-gongkai",
      "/zh/jinkou",
    ]);
  });

  it("lists the home page and dashboard in en and nl with hreflang alternates", () => {
    const languages = { en: `${SITE}/en`, nl: `${SITE}/nl` };
    expect(byUrl.get(`${SITE}/en`)).toEqual({ url: `${SITE}/en`, alternates: { languages } });
    expect(byUrl.get(`${SITE}/nl`)).toEqual({ url: `${SITE}/nl`, alternates: { languages } });
    expect(byUrl.get(`${SITE}/nl/dashboard`)?.alternates?.languages).toEqual({
      en: `${SITE}/en/dashboard`,
      nl: `${SITE}/nl/dashboard`,
    });
  });

  it("lists /data and /evaluation in English only and the legal pages in en, nl and zh", () => {
    expect(byUrl.get(`${SITE}/en/data`)).toEqual({ url: `${SITE}/en/data` });
    expect(byUrl.get(`${SITE}/en/evaluation`)).toEqual({ url: `${SITE}/en/evaluation` });
    expect(byUrl.has(`${SITE}/nl/evaluation`)).toBe(false);
    // The synthetic example page exists only in test builds and is never listed.
    expect([...byUrl.keys()].some((u) => u.includes("/evaluation/"))).toBe(false);
    expect(byUrl.has(`${SITE}/nl/data`)).toBe(false);
    expect(byUrl.get(`${SITE}/zh/privacy`)?.alternates?.languages).toEqual({
      en: `${SITE}/en/privacy`,
      nl: `${SITE}/nl/privacy`,
      "zh-Hans": `${SITE}/zh/privacy`,
    });
    for (const page of ["about", "disclaimer", "colofon"]) {
      expect(byUrl.has(`${SITE}/zh/${page}`), page).toBe(true);
    }
  });

  it("lists every Notification in en and nl with its last change", () => {
    const path = "/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-kaas";
    expect(byUrl.get(`${SITE}/nl${path}`)).toEqual({
      url: `${SITE}/nl${path}`,
      lastModified: "2026-10-24T10:00:00.000Z",
      alternates: { languages: { en: `${SITE}/en${path}`, nl: `${SITE}/nl${path}` } },
    });
    expect(byUrl.has(`${SITE}/en${path}`)).toBe(true);
  });

  it("leaves out pages that are not indexed", () => {
    expect(entries).toHaveLength(2 + 2 + 1 + 1 + 4 * 3 + 1 + 2);
    expect(entries.some((e) => /\/(search|alerts)/.test(e.url))).toBe(false);
  });
});
