import { describe, expect, it } from "vitest";
import { parseInline, zhPageProblems, type ZhPage } from "./zh-pages";

describe("parseInline", () => {
  it("turns [text](url) into links and keeps the rest as text", () => {
    expect(
      parseInline("见 [NVWA 检查说明](https://www.nvwa.nl/ondernemers/x) 和 [订阅](/zh/alerts)。"),
    ).toEqual([
      { text: "见 " },
      { text: "NVWA 检查说明", href: "https://www.nvwa.nl/ondernemers/x" },
      { text: " 和 " },
      { text: "订阅", href: "/zh/alerts" },
      { text: "。" },
    ]);
  });

  it("leaves text without links and stray brackets alone", () => {
    expect(parseInline("第 44 条 [Gezondheidswet]")).toEqual([{ text: "第 44 条 [Gezondheidswet]" }]);
  });
});

const DRAFT: ZhPage = {
  title: "NVWA 检查实务",
  navLabel: "NVWA 检查",
  description: "NVWA 怎样检查餐饮企业。",
  reviewedOn: null,
  officialLinks: [
    { title: "NVWA 检查是怎样进行的", url: "https://www.nvwa.nl/ondernemers/x", lang: "nl" },
  ],
  sections: [{ heading: "检查前", body: [], outline: ["检查通常不提前通知"] }],
};

const REVIEWED: ZhPage = {
  ...DRAFT,
  reviewedOn: "2026-10-20",
  sections: [
    {
      heading: "检查前",
      body: ["见 [NVWA](https://www.nvwa.nl/ondernemers/x)。", { list: ["一", "[订阅](/zh/alerts)"] }],
    },
  ],
};

const TODAY = "2026-10-25";

// Type-level: `pnpm typecheck` fails when a page leaves out its review date or official
// links, or when the first official link is not an NVWA page.
const { reviewedOn: _reviewedOn, ...withoutReviewedOn } = DRAFT;
// @ts-expect-error reviewedOn is required (null for a draft)
const _noReview: ZhPage = withoutReviewedOn;
// @ts-expect-error at least one official link
const _noLinks: ZhPage = { ...DRAFT, officialLinks: [] };
const _notNvwa: ZhPage = {
  ...DRAFT,
  // @ts-expect-error the first official link is an NVWA page
  officialLinks: [{ title: "法律", url: "https://wetten.overheid.nl/x", lang: "nl" }],
};
void [_reviewedOn, _noReview, _noLinks, _notNvwa];

describe("zhPageProblems", () => {
  it("accepts a draft with an outline and a reviewed page with prose", () => {
    expect(zhPageProblems(DRAFT, TODAY)).toEqual([]);
    expect(zhPageProblems(REVIEWED, TODAY)).toEqual([]);
  });

  it("rejects a review date that is not a real date or lies in the future", () => {
    expect(zhPageProblems({ ...REVIEWED, reviewedOn: "2026-02-30" }, TODAY)).toEqual([
      "reviewedOn 2026-02-30 is not a date",
    ]);
    expect(zhPageProblems({ ...REVIEWED, reviewedOn: "2026-10-26" }, TODAY)).toEqual([
      "reviewedOn 2026-10-26 is in the future",
    ]);
  });

  it("rejects a reviewed page that still has an outline or an empty section", () => {
    expect(
      zhPageProblems({ ...REVIEWED, sections: [{ heading: "检查前", body: [], outline: ["x"] }] }, TODAY),
    ).toEqual(['section "检查前" still has an outline', 'section "检查前" has no text']);
  });

  it("only allows links to official Dutch pages and to this site's zh pages", () => {
    const page: ZhPage = {
      ...REVIEWED,
      sections: [{ heading: "检查前", body: ["[某公司](https://example.com/a) 与 [英文页](/en/search)"] }],
    };
    expect(zhPageProblems(page, TODAY)).toEqual([
      "link https://example.com/a is not an official page",
      "link /en/search is not an official page",
    ]);
    const draft: ZhPage = {
      ...DRAFT,
      sections: [{ heading: "检查前", body: [], outline: ["[某公司](https://example.com/b)"] }],
    };
    expect(zhPageProblems(draft, TODAY)).toEqual(["link https://example.com/b is not an official page"]);
  });

  it("requires the first official link to be an NVWA page", () => {
    const page = {
      ...DRAFT,
      officialLinks: [{ title: "法律", url: "https://wetten.overheid.nl/BWBR0001", lang: "nl" }],
    } as unknown as ZhPage;
    expect(zhPageProblems(page, TODAY)).toEqual(["the first official link must be an NVWA page"]);
  });
});
