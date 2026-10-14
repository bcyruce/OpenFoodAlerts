import { describe, expect, it } from "vitest";
import { footerLinks, isCurrentNav, navItems } from "./site-links";

describe("navItems", () => {
  it("links the four main sections in en and nl", () => {
    expect(navItems("nl")).toEqual([
      { key: "home", href: "/nl" },
      { key: "dashboard", href: "/nl/dashboard" },
      { key: "search", href: "/nl/search" },
      { key: "subscribe", href: "/nl/alerts" },
    ]);
  });

  it("only links pages that exist in zh", () => {
    expect(navItems("zh")).toEqual([{ key: "subscribe", href: "/zh/alerts" }]);
  });
});

describe("isCurrentNav", () => {
  it("marks home only on the home page and sections on their subpages", () => {
    const [home, dashboard, , subscribe] = navItems("en");
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
