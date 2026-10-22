import { describe, expect, it } from "vitest";
import { homePath, localesForPath } from "@/i18n/routing";
import { footerLinks, isCurrentNav, navItems } from "./site-links";

describe("navItems", () => {
  it("links the main sections in en and nl; Evaluation is English only (spec §9)", () => {
    expect(navItems("nl")).toEqual([
      { key: "home", href: "/nl" },
      { key: "dashboard", href: "/nl/dashboard" },
      { key: "search", href: "/nl/search" },
      { key: "evaluation", href: "/en/evaluation", hrefLang: "en" },
      { key: "subscribe", href: "/nl/alerts" },
    ]);
    expect(navItems("en")[3]).toEqual({ key: "evaluation", href: "/en/evaluation" });
  });

  it("links the Chinese module and the subscription flow in zh", () => {
    expect(navItems("zh")).toEqual([
      { key: "home", href: "/zh" },
      { key: "subscribe", href: "/zh/alerts" },
    ]);
  });
});

describe("zh routing", () => {
  it("keeps the Chinese module pages in zh only and links every home page", () => {
    expect(localesForPath("nvwa-jiancha")).toEqual(["zh"]);
    expect(localesForPath("jinkou/x")).toEqual(["zh"]);
    expect(localesForPath("jinggao")).toEqual(["zh"]);
    expect(localesForPath("jinggao/2")).toEqual(["zh"]);
    expect(localesForPath("")).toEqual(["en", "nl", "zh"]);
    expect(localesForPath("alerts/confirm")).toEqual(["en", "nl", "zh"]);
    expect(localesForPath("dashboard")).toEqual(["en", "nl"]);
    expect(localesForPath("evaluation")).toEqual(["en"]);
    expect(localesForPath("evaluation/example")).toEqual(["en"]);
    expect(homePath("zh")).toBe("/zh");
    expect(homePath("nl")).toBe("/nl");
  });
});

describe("isCurrentNav", () => {
  it("marks home only on the home page and sections on their subpages", () => {
    const [home, dashboard, , evaluation, subscribe] = navItems("en");
    expect(isCurrentNav(evaluation, "/en/evaluation")).toBe(true);
    expect(isCurrentNav(home, "/en")).toBe(true);
    expect(isCurrentNav(home, "/en/dashboard")).toBe(false);
    expect(isCurrentNav(dashboard, "/en/dashboard")).toBe(true);
    expect(isCurrentNav(subscribe, "/en/alerts/confirm")).toBe(true);
    expect(isCurrentNav(subscribe, "/en/alertsx")).toBe(false);
  });
});

describe("footerLinks", () => {
  it("links the data and legal pages; /data exists in English only (spec §9)", () => {
    expect(footerLinks("nl")).toEqual([
      { key: "data", href: "/en/data", hrefLang: "en" },
      { key: "about", href: "/nl/about" },
      { key: "privacy", href: "/nl/privacy" },
      { key: "disclaimerLink", href: "/nl/disclaimer" },
      { key: "colofon", href: "/nl/colofon" },
    ]);
    expect(footerLinks("en")[0]).toEqual({ key: "data", href: "/en/data" });
    expect(footerLinks("zh")[1]).toEqual({ key: "about", href: "/zh/about" });
  });
});
