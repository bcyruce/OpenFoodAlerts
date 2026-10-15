/**
 * Content model of the Chinese module (spec §9, ticket 32): `/zh` and its four guide pages.
 * The prose lives in `content/zh/*.ts`, one file per page, written or reviewed by the owner
 * (an LLM may only draft translations). Pure and client-safe.
 */

/** One piece of a paragraph: plain text, or a link when `href` is set. */
export type InlinePart = { text: string; href?: string };

const LINK = /\[([^\]\n]+)\]\(([^)\s]+)\)/g;

/** Splits a paragraph on Markdown-style `[text](url)` links; nothing else is parsed. */
export function parseInline(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ text: match[1], href: match[2] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** A calendar date, YYYY-MM-DD. */
export type IsoDate = `${number}-${number}-${number}`;

/** NVWA pages: www.nvwa.nl and its subdomains, such as openbare-inspectieresultaten.nvwa.nl. */
export type NvwaUrl = `https://${string}nvwa.nl/${string}`;

/**
 * Official Dutch pages a zh page may link to (spec §9: only the Netherlands and NVWA): NVWA,
 * the law texts on wetten.overheid.nl and the central government sites.
 */
export type OfficialUrl =
  | NvwaUrl
  | `https://wetten.overheid.nl/${string}`
  | `https://www.rijksoverheid.nl/${string}`
  | `https://www.government.nl/${string}`;

export type OfficialLink<U extends OfficialUrl = OfficialUrl> = {
  /** The link text, in Chinese. */
  title: string;
  url: U;
  /** Language of the linked page (`hreflang`). */
  lang: "nl" | "en";
};

/** A paragraph (`[text](url)` links allowed) or a bulleted list of such lines. */
export type ZhBlock = string | { list: readonly string[] };

export type ZhSection = {
  heading: string;
  /** The text of the section. May stay empty while the page is a draft. */
  body: readonly ZhBlock[];
  /**
   * Draft only: what the section should cover (written by the agent, not reviewed). Shown
   * in a marked box; remove it when the section is written.
   */
  outline?: readonly string[];
};

/**
 * One page of the Chinese module. `reviewedOn` and `officialLinks` are required (spec §9:
 * every page has a review date and links to the official pages):
 * - `reviewedOn`: the date the owner last wrote or checked the text, or `null` while the
 *   page is a draft. A draft shows the "内容待审核" notice, is `noindex` and stays out of
 *   the sitemap. The key itself cannot be left out.
 * - `officialLinks`: at least one, and the first is an NVWA page.
 */
export type ZhPage = {
  /** `<h1>` and `<title>`. */
  title: string;
  /** Short name for the module navigation. */
  navLabel: string;
  /** Meta description and the summary on `/zh`. */
  description: string;
  reviewedOn: IsoDate | null;
  officialLinks: readonly [OfficialLink<NvwaUrl>, ...OfficialLink[]];
  sections: readonly ZhSection[];
};

export function isDraft(page: ZhPage): boolean {
  return page.reviewedOn === null;
}

const OFFICIAL =
  /^https:\/\/(([a-z0-9-]+\.)*nvwa\.nl|wetten\.overheid\.nl|www\.rijksoverheid\.nl|www\.government\.nl)\//;
const NVWA = /^https:\/\/([a-z0-9-]+\.)*nvwa\.nl\//;
/** This site's Chinese pages: `/zh`, `/zh/…`, optionally with a fragment. */
const INTERNAL = /^\/zh(\/[a-z0-9/-]*)?(#[\w-]+)?$/;

function isRealDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function blockLines(block: ZhBlock): readonly string[] {
  return typeof block === "string" ? [block] : block.list;
}

/**
 * What is wrong with a page, as messages for the content test (`[]` = fine). `today` is
 * the Amsterdam date YYYY-MM-DD. The types already require the fields; this checks what
 * types cannot: real dates, a reviewed page without draft leftovers, and links that only
 * go to official Dutch pages or to this site's zh pages.
 */
export function zhPageProblems(page: ZhPage, today: string): string[] {
  const problems: string[] = [];
  if (page.reviewedOn !== null) {
    if (!isRealDate(page.reviewedOn)) problems.push(`reviewedOn ${page.reviewedOn} is not a date`);
    else if (page.reviewedOn > today) problems.push(`reviewedOn ${page.reviewedOn} is in the future`);
  }
  if (!page.title.trim() || !page.navLabel.trim() || !page.description.trim()) {
    problems.push("title, navLabel and description must not be empty");
  }
  const [first] = page.officialLinks;
  if (!first || !NVWA.test(first.url)) problems.push("the first official link must be an NVWA page");
  for (const link of page.officialLinks) {
    if (!OFFICIAL.test(link.url)) problems.push(`official link ${link.url} is not an official page`);
  }
  for (const section of page.sections) {
    if (!section.heading.trim()) problems.push("a section has no heading");
    if (page.reviewedOn !== null) {
      if (section.outline?.length) problems.push(`section "${section.heading}" still has an outline`);
      if (section.body.length === 0) problems.push(`section "${section.heading}" has no text`);
    }
    for (const line of [...section.body.flatMap(blockLines), ...(section.outline ?? [])]) {
      for (const { href } of parseInline(line)) {
        if (href !== undefined && !OFFICIAL.test(href) && !INTERNAL.test(href)) {
          problems.push(`link ${href} is not an official page`);
        }
      }
    }
  }
  return problems;
}
