// Smoke tests for /dashboard and /api/stats, against the fixtures loaded by `make
// web-fixtures`. They use `months=all` so that the fixtures' publication dates never fall
// out of the default 12-month period. Three RASFF Notifications are "fruits and vegetables"
// (18448): pesticide residues from Türkiye and Uzbekistan, mycotoxins from Türkiye. (The
// herbs-and-spices fixture, 2026.5644, has RASFF product type "animals", so it is non-food
// and never counted; S1's numbers are covered by lib/stats.test.ts.)
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const FRUIT = "18448";
const HERBS = "18450";

async function tableText(page: Page, testId: string): Promise<string> {
  const table = page.getByTestId(testId);
  await table.locator("summary").click();
  return (await table.locator("table").textContent()) ?? "";
}

test("S1: herbs and spices over the last 12 months is a URL", async ({ page }) => {
  await page.goto(`/en/dashboard?product=${HERBS}&months=12`);
  // 12 months is the default period, so it is left out of the canonical URL.
  await expect(page).toHaveURL(new RegExp(`/en/dashboard\\?product=${HERBS}$`));
  await expect(
    page.getByTestId("filter-product").getByRole("checkbox", { name: "herbs and spices" }),
  ).toBeChecked();
  await expect(page.getByRole("combobox", { name: "Period" })).toHaveValue("12");
});

test("shows a Product category from the URL with a heatmap and data tables", async ({ page }) => {
  await page.goto(`/en/dashboard?product=${FRUIT}&months=all`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  await expect(page.getByTestId("total-rasff")).toContainText("3 notifications");
  await expect(page.getByTestId("total-nvwa")).toContainText("No notifications");
  const heatmap = await tableText(page, "table-heatmap-rasff");
  expect(heatmap).toContain("pesticide residues · Türkiye");
  expect(heatmap).toContain("pesticide residues · Uzbekistan");
  expect(heatmap).toContain("mycotoxins · Türkiye");
  // Every chart is drawn by ECharts on the client, next to its table.
  await expect(page.getByTestId("chart-heatmap-rasff").locator("svg")).toBeVisible();
  await expect(page.getByTestId("chart-timeseries").locator("svg")).toBeVisible();
});

test("changing a filter with the keyboard updates the URL and the data tables", async ({ page }) => {
  await page.goto("/en/dashboard?months=all");
  await expect(page.getByTestId("chart-timeseries").locator("svg")).toBeVisible();
  const before = await tableText(page, "table-top-hazard-rasff");
  expect(before).toContain("pesticide residues");
  expect(before).toContain("migration");

  await page.getByTestId("filter-product").locator("summary").click();
  const fruit = page
    .getByTestId("filter-product")
    .getByRole("checkbox", { name: "fruits and vegetables" });
  await fruit.focus();
  await page.keyboard.press("Space");

  await expect(page).toHaveURL(new RegExp(`/en/dashboard\\?product=${FRUIT}&months=all$`));
  await expect(page.getByTestId("total-rasff")).toContainText("3 notifications");
  const after = page.getByTestId("table-top-hazard-rasff").locator("table");
  await expect(after).toContainText("pesticide residues");
  await expect(after).not.toContainText("migration");

  // The address bar can be shared: loading it again gives the same view.
  await page.reload();
  await expect(page.getByTestId("total-rasff")).toContainText("3 notifications");
});

test("filters by Source and keeps official-only in the URL", async ({ page }) => {
  await page.goto("/en/dashboard?months=all");
  await expect(page.getByTestId("chart-timeseries").locator("svg")).toBeVisible();
  const header = await tableText(page, "table-timeseries");
  expect(header).toContain("NVWA");

  const nvwa = page.getByTestId("dashboard-filters").getByRole("checkbox", { name: "NVWA" });
  await nvwa.focus();
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/\/en\/dashboard\?source=openfda&source=rasff&months=all$/);
  await expect(page.getByTestId("source-nvwa")).toHaveCount(0);
  await expect(page.getByTestId("table-timeseries").locator("thead")).not.toContainText("NVWA");

  await page.getByRole("checkbox", { name: "Official classifications only" }).check();
  await expect(page).toHaveURL(
    /\/en\/dashboard\?source=openfda&source=rasff&official_only=1&months=all$/,
  );
  await expect(page.getByTestId("dashboard-status")).toHaveText("Charts updated.");
});

test("picks a period and canonicalises the URL", async ({ page }) => {
  await page.goto(`/en/dashboard?months=12&source=&product[]=${FRUIT}`);
  await expect(page).toHaveURL(new RegExp(`/en/dashboard\\?product=${FRUIT}$`));
  await page.getByRole("combobox", { name: "Period" }).selectOption("all");
  await expect(page).toHaveURL(new RegExp(`/en/dashboard\\?product=${FRUIT}&months=all$`));
  await expect(page.getByTestId("total-rasff")).toContainText("3 notifications");
});

test("/api/stats returns the statistics per Source", async ({ request }) => {
  const response = await request.get(`/api/stats?product[]=${FRUIT}&months=all&locale=nl`);
  expect(response.ok()).toBe(true);
  const body = await response.json();
  expect(body.filters.productCategories).toEqual([Number(FRUIT)]);
  expect(body.sources.map((s: { source: string }) => s.source)).toEqual(["rasff", "nvwa", "openfda"]);
  const rasff = body.sources[0];
  expect(rasff.total).toBe(3);
  // Labels in Dutch; most Notifications first.
  expect(rasff.top.country).toEqual([
    { value: "TR", label: "Turkije", count: 2, ai: 0 },
    { value: "UZ", label: "Oezbekistan", count: 1, ai: 0 },
  ]);
  expect(rasff.heatmap[0]).toMatchObject({
    hazard: { label: "mycotoxins" },
    country: { value: "TR" },
    total: 1,
  });
  expect(rasff.monthly).toHaveLength(body.months.length);
});

test("is available in Dutch, not in Chinese", async ({ page }) => {
  await page.goto("/nl/dashboard?months=all");
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect(page.getByRole("heading", { name: "Meldingen per maand" })).toBeVisible();
  const zh = await page.goto("/zh/dashboard");
  expect(zh?.status()).toBe(404);
});

test("has no detectable accessibility violations", async ({ page }) => {
  await page.goto(`/en/dashboard?product=${FRUIT}&months=all`);
  await expect(page.getByTestId("chart-heatmap-rasff").locator("svg")).toBeVisible();
  for (const details of await page.locator("details").all()) {
    await details.evaluate((d) => ((d as HTMLDetailsElement).open = true));
  }
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});
