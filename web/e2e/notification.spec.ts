// Smoke tests for the Notification detail page, against the fixtures loaded by
// `make web-fixtures` (pipeline/tests/fixtures/openfda + e2e/fixtures/openfda).
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGE = "/en/n/openfda/H-0015-2027";

test("shows an openFDA Notification with its official fields and history", async ({ page }) => {
  const response = await page.goto(PAGE);
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("QUESO PALMITA");

  const official = page.getByTestId("official-fields");
  await expect(official.getByRole("heading", { name: "Official information" })).toBeVisible();
  await expect(official).toContainText("Class II");
  await expect(official).toContainText("Undeclared milk, cheese declared");
  await expect(page.getByTestId("source-fields")).toContainText("QUESO PALMITA GP LLC");
  await expect(
    official.getByRole("link", { name: /View the official record/ }),
  ).toHaveAttribute("href", /api\.fda\.gov\/food\/enforcement\.json\?search=recall_number/);

  await expect(page.getByTestId("ai-fields")).toContainText("No AI classifications yet.");

  const history = page.getByTestId("version-history");
  await expect(history.getByRole("heading", { name: /Version 2/ })).toBeVisible();
  await expect(history).toContainText("Substantial change");
  const change = history.getByRole("row", { name: /Status/ });
  await expect(change).toContainText("Ongoing");
  await expect(change).toContainText("Completed");
  await expect(history.getByRole("heading", { name: /Version 1/ })).toBeVisible();

  await expect(page.getByTestId("attribution")).toHaveText(
    "Source: U.S. Food and Drug Administration via openFDA. Not endorsed by FDA.",
  );
  await expect(page.getByRole("link", { name: "Report an error on this page" })).toHaveAttribute(
    "href",
    /github\.com\/.+\/issues\/new\?/,
  );
});

test("is indexable and has Open Graph metadata", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page).toHaveTitle(/QUESO PALMITA \(H-0015-2027\) \| OpenFoodAlerts/);
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await expect(page.locator('meta[property="og:type"]')).toHaveAttribute("content", "article");
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
    "content",
    /QUESO PALMITA/,
  );
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/en\/n\/openfda\/H-0015-2027$/);
  await expect(page.locator('link[rel="alternate"][hreflang="nl"]')).toHaveAttribute(
    "href",
    /\/nl\/n\/openfda\/H-0015-2027$/,
  );
});

test("renders the Dutch interface under /nl", async ({ page }) => {
  await page.goto("/nl/n/openfda/H-0015-2027");
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect(page.getByRole("heading", { name: "Officiële informatie" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Versiegeschiedenis" })).toBeVisible();
  await expect(page.getByRole("link", { name: "English" })).toHaveAttribute("href", PAGE);
});

for (const [what, path] of [
  ["non-food", "/en/n/openfda/Z-9001-2027"],
  ["pending Product type", "/en/n/openfda/Z-9002-2027"],
  ["unknown key", "/en/n/openfda/H-9999-2027"],
  ["unknown Source", "/en/n/xyz/H-0015-2027"],
]) {
  test(`returns 404 for a ${what}`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Notification not found");
  });
}

test("is keyboard-friendly: the first Tab reaches the skip link", async ({ page }) => {
  await page.goto(PAGE);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
});

test("has no WCAG 2 A/AA violations (axe)", async ({ page }) => {
  await page.goto(PAGE);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});

test("redirects / to a locale", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/(en|nl)$/);
});
