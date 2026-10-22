// Smoke tests for /zh/jinggao (ticket 33, spec §9): NVWA food warnings with their Chinese
// AI summary. Data from `make web-fixtures`: the NVWA fixture pages (all with fewer than
// one real page of warnings, so `make smoke` pages by OFA_ZH_WARNINGS_PAGE_SIZE = 5) and
// the hand-written summary_zh row of the coriander warning
// (e2e/fixtures/ai/classifications.json).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PAGE_SIZE = Number(process.env.OFA_ZH_WARNINGS_PAGE_SIZE) || 20;
const CORIANDER_KEY = "actueel/nieuws/2026/10/13/veiligheidswaarschuwing-cook-korianderzaad-gemalen";
const CORIANDER_SUMMARY = "Cook 牌磨碎芫荽籽可能含有沙门氏菌，请勿食用。";

// Visible only: after a client-side navigation the router keeps the previous page in the
// DOM, hidden.
const warnings = (page: Page) => page.getByTestId("zh-warning").filter({ visible: true });

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test("/zh/jinggao lists NVWA food warnings with the Chinese AI summary, not graded", async ({ page }) => {
  const response = await page.goto("/zh/jinggao");
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("NVWA 食品警告中文摘要");
  await expect(page).toHaveTitle("NVWA 食品警告中文摘要 | OpenFoodAlerts");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/zh\/jinggao$/);
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);

  const items = warnings(page);
  await expect(items).toHaveCount(PAGE_SIZE);
  // Newest first.
  const dates = await items.locator("time").evaluateAll((els) => els.map((el) => el.getAttribute("datetime")!));
  expect(dates).toEqual([...dates].sort().reverse());

  // Every warning: the Dutch title, "未分级", the official NVWA link and the English detail page.
  for (const item of await items.all()) {
    await expect(item.getByRole("heading", { level: 2 })).toHaveAttribute("lang", "nl");
    await expect(item.getByTestId("zh-warning-severity")).toHaveText("未分级");
    await expect(item.getByTestId("zh-warning-official")).toHaveAttribute("href", /^https:\/\/www\.nvwa\.nl\//);
    await expect(item.getByTestId("zh-warning-official")).toHaveAttribute("hreflang", "nl");
    await expect(item.getByTestId("zh-warning-detail")).toHaveAttribute("href", /^\/en\/n\/nvwa\//);
  }
  // No severity other than "未分级" (ADR 0006).
  const text = (await page.getByTestId("zh-warnings").textContent()) ?? "";
  expect(text.replaceAll("严重度：未分级", "")).not.toMatch(/严重|高风险|危险|一级|分级/);

  const coriander = items.filter({ has: page.locator(`a[href="/en/n/nvwa/${CORIANDER_KEY}"]`) });
  await expect(coriander.getByRole("heading")).toHaveText("Veiligheidswaarschuwing Cook korianderzaad gemalen");
  await expect(coriander.locator("time")).toHaveAttribute("datetime", "2026-10-13T07:36:00.000Z");
  await expect(coriander.locator("time")).toHaveText("2026年10月13日");
  const summary = coriander.getByTestId("zh-warning-summary");
  await expect(summary).toContainText("中文摘要（AI 生成）");
  await expect(summary).toContainText(CORIANDER_SUMMARY);
  const badge = summary.getByTestId("ai-badge");
  await expect(badge.getByRole("button", { name: "AI 生成" })).toHaveAccessibleDescription(
    /^由 fixture 于 .+ 生成，提示 v\d+。 摘要不在测试集上计分。 以官方原文为准。$/,
  );
  await badge.getByRole("button").focus();
  await expect(badge.getByTestId("ai-badge-popup").getByRole("link", { name: "官方来源" })).toHaveAttribute(
    "href",
    `https://www.nvwa.nl/${CORIANDER_KEY}`,
  );

  // The others have no Chinese summary yet: listed anyway, pointing to the official text.
  const without = items.filter({ hasNot: page.getByTestId("zh-warning-summary") });
  await expect(without.first().getByTestId("zh-warning-no-summary")).toHaveText(/^暂无中文摘要/);
  await expect(page.getByTestId("ai-badge")).toHaveCount(1);

  // Spec §11.3: the ad box is allowed on /zh/*, last, with utm_medium=zh_box.
  await expect(page.getByTestId("ad-box")).toHaveCount(1);
  await expect(page.locator("main > :last-child")).toHaveAttribute("data-testid", "ad-box");
  expect(await page.getByTestId("ad-box").getByRole("link").getAttribute("href")).toContain("utm_medium=zh_box");
});

test("/zh/jinggao pages through the warnings; pages past the end and non-canonical pages are 404", async ({
  page,
}) => {
  await page.goto("/zh/jinggao");
  const pagination = page.getByRole("navigation", { name: "分页" });
  await expect(pagination.getByRole("link", { name: "上一页" })).toHaveCount(0);
  const firstPage = await warnings(page).locator("h2").allTextContents();
  await pagination.getByRole("link", { name: "下一页" }).click();
  await expect(page).toHaveURL(/\/zh\/jinggao\/2$/);
  await expect(page).toHaveTitle("NVWA 食品警告中文摘要（第 2 页） | OpenFoodAlerts");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/zh\/jinggao\/2$/);
  await expect(page.getByRole("navigation", { name: "分页" })).toContainText("第 2 页");
  await expect(warnings(page).first().locator("h2")).not.toHaveText(firstPage[0]);
  const second = await warnings(page).locator("h2").allTextContents();
  expect(second.length).toBeGreaterThan(0);
  expect(second.filter((t) => firstPage.includes(t))).toEqual([]);
  await expect(page.getByTestId("ad-box").filter({ visible: true })).toHaveCount(1);

  const back = page.getByRole("navigation", { name: "分页" }).getByRole("link", { name: "上一页" });
  await expect(back).toHaveAttribute("href", "/zh/jinggao");

  for (const path of ["/zh/jinggao/1", "/zh/jinggao/02", "/zh/jinggao/x", "/zh/jinggao/999", "/en/jinggao", "/nl/jinggao/2"]) {
    expect((await page.goto(path))?.status(), path).toBe(404);
  }
});

for (const path of ["/zh/jinggao", "/zh/jinggao/2"]) {
  test(`${path} has no WCAG 2 A/AA violations (axe)`, async ({ page }) => {
    await page.goto(path);
    await expectNoAxeViolations(page);
  });
}

test("the Chinese module links the warning stream", async ({ page }) => {
  await page.goto("/zh");
  await expect(page.getByTestId("zh-warnings-card").getByRole("link", { name: "NVWA 食品警告中文摘要" })).toHaveAttribute(
    "href",
    "/zh/jinggao",
  );
  await page.goto("/zh/jinggao");
  const moduleNav = page.getByRole("navigation", { name: "中文指南" });
  await expect(moduleNav.getByRole("link", { name: "NVWA 警告摘要" })).toHaveAttribute("aria-current", "page");
  // zh only: no English or Dutch version to switch to.
  await expect(page.getByRole("link", { name: "English" })).toHaveCount(0);
  await page.goto("/zh/jinkou");
  await expect(page.getByRole("navigation", { name: "中文指南" }).getByRole("link", { name: "NVWA 警告摘要" })).toHaveAttribute(
    "href",
    "/zh/jinggao",
  );
});

test("/zh/jinggao works with the keyboard", async ({ page }) => {
  await page.goto("/zh/jinggao");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳到主要内容" })).toBeFocused();
  const next = page.getByRole("navigation", { name: "分页" }).getByRole("link", { name: "下一页" });
  for (let i = 0; i < 80 && !(await next.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(next).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/zh\/jinggao\/2$/);
});

test("/sitemap.xml lists the first page of the warning stream", async ({ request }) => {
  const xml = await (await request.get("/sitemap.xml")).text();
  expect(xml).toContain("<loc>https://openfoodalerts.nl/zh/jinggao</loc>");
  expect(xml).not.toContain("/zh/jinggao/");
});
