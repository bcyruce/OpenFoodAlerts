// The content of the Chinese module (content/zh/*.ts) against the rules of spec §9: every
// page has a review date (or is an explicit draft) and official links, and links only to
// official Dutch pages. Run after every content edit: `pnpm test zh-content`.
import { describe, expect, it } from "vitest";
import { ZH_HOME, ZH_PAGES } from "@/content/zh";
import { ZH_MODULE_PAGES } from "@/i18n/routing";
import { zhPageProblems, type ZhPage } from "./zh-pages";

const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Amsterdam" }).format(new Date());

describe("Chinese module content", () => {
  it("has a page for every zh module route", () => {
    expect(Object.keys(ZH_PAGES).sort()).toEqual([...ZH_MODULE_PAGES].sort());
  });

  const pages: [string, ZhPage][] = [
    ["/zh", ZH_HOME],
    ...Object.entries(ZH_PAGES).map(([slug, page]): [string, ZhPage] => [`/zh/${slug}`, page]),
  ];
  it.each(pages)("%s has a review date or is a draft, official links and only official links", (_, page) => {
    expect(zhPageProblems(page, today)).toEqual([]);
    expect(page.officialLinks.length).toBeGreaterThan(0);
  });
});
