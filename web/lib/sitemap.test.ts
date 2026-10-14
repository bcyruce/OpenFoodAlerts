import { describe, expect, it } from "vitest";
import { buildSitemap } from "./sitemap";

const SITE = "https://openfoodalerts.nl";

describe("buildSitemap", () => {
  const entries = buildSitemap(SITE, [
    {
      source: "nvwa",
      key: "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-kaas",
      lastChangedAt: "2026-10-24T10:00:00.000Z",
    },
  ]);
  const byUrl = new Map(entries.map((e) => [e.url, e]));

  it("lists the home page and dashboard in en and nl with hreflang alternates", () => {
    const languages = { en: `${SITE}/en`, nl: `${SITE}/nl` };
    expect(byUrl.get(`${SITE}/en`)).toEqual({ url: `${SITE}/en`, alternates: { languages } });
    expect(byUrl.get(`${SITE}/nl`)).toEqual({ url: `${SITE}/nl`, alternates: { languages } });
    expect(byUrl.get(`${SITE}/nl/dashboard`)?.alternates?.languages).toEqual({
      en: `${SITE}/en/dashboard`,
      nl: `${SITE}/nl/dashboard`,
    });
  });

  it("lists /data in English only and the legal pages in en, nl and zh", () => {
    expect(byUrl.get(`${SITE}/en/data`)).toEqual({ url: `${SITE}/en/data` });
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
    expect(entries).toHaveLength(2 + 2 + 1 + 4 * 3 + 2);
    expect(entries.some((e) => /\/(search|alerts)/.test(e.url))).toBe(false);
  });
});
