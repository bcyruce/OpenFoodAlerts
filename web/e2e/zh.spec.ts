// Smoke tests for the Chinese module (ticket 32, spec §9): /zh and the four guide pages.
// The text is the owner's (content/zh/*.ts) and changes, so the checks read it from there
// instead of repeating it: a page is either reviewed (review date shown) or a draft (draft
// notice shown, noindex).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { ZH_HOME, ZH_PAGES } from "../content/zh";

const PAGES = [
  { path: "/zh", page: ZH_HOME },
  ...Object.entries(ZH_PAGES).map(([slug, page]) => ({ path: `/zh/${slug}`, page })),
];
const GUIDE_PATHS = Object.keys(ZH_PAGES).map((slug) => `/zh/${slug}`);

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

for (const { path, page: content } of PAGES) {
  test(`${path} is a Chinese page with its review state, official links and the ad box`, async ({
    page,
  }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(content.title);
    await expect(page).toHaveTitle(`${content.title} | OpenFoodAlerts`);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", new RegExp(`${path}$`));
    await expect(page.locator('link[rel="alternate"][hreflang]')).toHaveCount(0);

    if (content.reviewedOn === null) {
      await expect(page.getByRole("note", { name: "内容待审核" })).toBeVisible();
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
    } else {
      await expect(page.getByTestId("zh-draft-notice")).toHaveCount(0);
      await expect(page.getByTestId("zh-reviewed-on").locator("time")).toHaveAttribute(
        "datetime",
        content.reviewedOn,
      );
      await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
      await expect(page.getByTestId("zh-outline")).toHaveCount(0);
    }

    const official = page.getByTestId("zh-official-links");
    await expect(official.getByRole("heading", { name: "官方页面" })).toBeVisible();
    const links = official.getByRole("link");
    await expect(links).toHaveCount(content.officialLinks.length);
    await expect(links.first()).toHaveAttribute("href", /^https:\/\/([a-z0-9-]+\.)*nvwa\.nl\//);

    // Spec §11.3: the ad box is allowed on /zh/*, labelled, last, with utm_medium=zh_box.
    const ad = page.getByTestId("ad-box");
    await expect(ad).toHaveCount(1);
    await expect(page.locator("main > :last-child")).toHaveAttribute("data-testid", "ad-box");
    expect(await ad.getByRole("link").getAttribute("href")).toContain("utm_medium=zh_box");
    await expect(page.getByTestId("site-footer")).toContainText("本站非官方来源");
  });

  test(`${path} has no WCAG 2 A/AA violations (axe)`, async ({ page }) => {
    await page.goto(path);
    await expectNoAxeViolations(page);
  });
}

test("/zh links the guide pages and the Chinese subscription flow", async ({ page }) => {
  await page.goto("/zh");
  const guide = page.getByTestId("zh-guide-pages");
  for (const [slug, content] of Object.entries(ZH_PAGES)) {
    await expect(guide.getByRole("link", { name: content.title })).toHaveAttribute("href", `/zh/${slug}`);
  }
  await expect(page.getByTestId("zh-subscribe").getByRole("link")).toHaveAttribute("href", "/zh/alerts");

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "首页" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "订阅" })).toHaveAttribute("href", "/zh/alerts");
  // The site name leads to /zh; the language switch to the en/nl home pages.
  await expect(page.getByRole("banner").getByRole("link", { name: "OpenFoodAlerts" })).toHaveAttribute(
    "href",
    "/zh",
  );
  await expect(page.getByRole("link", { name: "English" })).toHaveAttribute("href", "/en");
});

test("the guide pages link each other and exist only in Chinese", async ({ page }) => {
  await page.goto("/zh/jinkou");
  const moduleNav = page.getByRole("navigation", { name: "中文指南" });
  // The guide pages and the warning stream /zh/jinggao (ticket 33).
  await expect(moduleNav.getByRole("link")).toHaveCount(GUIDE_PATHS.length + 1);
  await expect(moduleNav.getByRole("link", { name: ZH_PAGES.jinkou.navLabel })).toHaveAttribute(
    "aria-current",
    "page",
  );
  // No English or Dutch version to switch to.
  await expect(page.getByRole("link", { name: "English" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Nederlands" })).toHaveCount(0);

  for (const path of ["/en/jinkou", "/nl/nvwa-jiancha"]) {
    expect((await page.goto(path))?.status(), path).toBe(404);
  }
});

test("the Chinese module works with the keyboard", async ({ page }) => {
  await page.goto("/zh");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳到主要内容" })).toBeFocused();

  // Tab to the first guide page and follow it with Enter.
  const first = page.getByTestId("zh-guide-pages").getByRole("link").first();
  const target = await first.getAttribute("href");
  for (let i = 0; i < 30 && !(await first.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(first).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${target}$`));

  // The module navigation is reachable from there as well.
  const moduleNav = page.getByRole("navigation", { name: "中文指南" });
  const next = moduleNav.getByRole("link").nth(1);
  for (let i = 0; i < 30 && !(await next.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(next).toBeFocused();
});

test("/sitemap.xml lists the Chinese module pages once they are reviewed", async ({ request }) => {
  const xml = await (await request.get("/sitemap.xml")).text();
  for (const { path, page } of PAGES) {
    const loc = `<loc>https://openfoodalerts.nl${path}</loc>`;
    if (page.reviewedOn === null) expect(xml, path).not.toContain(loc);
    else expect(xml, path).toContain(loc);
  }
});
