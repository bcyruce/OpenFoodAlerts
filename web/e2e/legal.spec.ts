// Smoke tests for the data page and the legal pages (ticket 27): static pages, the
// locales each exists in, `lang`, the content the spec requires and an axe WCAG A/AA scan.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const LEGAL_PAGES = ["about", "privacy", "disclaimer", "colofon"] as const;
const LANG = { en: "en", nl: "nl", zh: "zh-Hans" } as const;

// The attribution texts of the sources table (migration 20261025000100_core.sql).
const ATTRIBUTIONS = [
  "Source: European Commission – RASFF Window; normalized and classified by OpenFoodAlerts, changes indicated.",
  "Source: Nederlandse Voedsel- en Warenautoriteit (NVWA). Unofficial; not endorsed by NVWA.",
  "Source: U.S. Food and Drug Administration via openFDA. Not endorsed by FDA.",
];

async function expectNoAxeViolations(page: Page) {
  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(scan.violations).toEqual([]);
}

for (const name of LEGAL_PAGES) {
  for (const locale of ["en", "nl", "zh"] as const) {
    test(`/${locale}/${name} renders with lang=${LANG[locale]} and passes axe`, async ({ page }) => {
      const response = await page.goto(`/${locale}/${name}`);
      expect(response?.status()).toBe(200);
      await expect(page.locator("html")).toHaveAttribute("lang", LANG[locale]);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
        "href",
        new RegExp(`/${locale}/${name}$`),
      );
      await expect(page.locator('link[rel="alternate"][hreflang="zh-Hans"]')).toHaveAttribute(
        "href",
        new RegExp(`/zh/${name}$`),
      );
      await expectNoAxeViolations(page);
    });
  }
}

test("the disclaimer states the spec's text, verbatim in Chinese", async ({ page }) => {
  await page.goto("/zh/disclaimer");
  await expect(page.getByTestId("disclaimer-statement")).toHaveText(
    "本站非官方来源，与 NVWA、欧盟委员会、FDA 无关联；信息可能延迟或有误；采取任何行动前请核对官方通报；AI 分类字段可能出错。",
  );
  await page.goto("/en/disclaimer");
  await expect(page.getByTestId("disclaimer-statement")).toContainText(
    "not affiliated with NVWA, the European Commission or FDA",
  );
  await expect(page.getByTestId("disclaimer-statement")).toContainText("AI classification fields may be wrong");
});

test("about discloses the SnelVink interest with one UTM text link and the review date", async ({
  page,
}) => {
  await page.goto("/en/about");
  await expect(page.getByRole("heading", { name: "Interest disclosure" })).toBeVisible();
  await expect(page.getByTestId("rules-reviewed")).toHaveText("Rules last reviewed on 25 October 2026.");
  const links = page.locator('main a[href*="snelvink.nl"]');
  await expect(links).toHaveCount(1);
  const href = await links.getAttribute("href");
  const url = new URL(href ?? "");
  expect(url.searchParams.get("utm_source")).toBe("openfoodalerts.nl");
  expect(url.searchParams.get("utm_medium")).toBe("about");
  expect(url.searchParams.get("utm_campaign")).toBe("v1");
  // No advertisement box on this page (spec §11.3 rule 3).
  await expect(page.locator("main aside")).toHaveCount(0);
});

test("privacy names the controller, processors, retention, rights and the AP; no cookies", async ({
  page,
  context,
}) => {
  await page.goto("/en/privacy");
  await expect(page.getByTestId("controller")).toBeVisible();
  await expect(page.getByTestId("processors")).toContainText("Brevo");
  const retention = page.getByTestId("retention");
  await expect(retention).toContainText("Deleted 7 days after the last request");
  await expect(retention).toContainText("Deleted within 30 days");
  await expect(retention).toContainText("12 months");
  await expect(page.getByRole("link", { name: "Autoriteit Persoonsgegevens" })).toHaveAttribute(
    "href",
    "https://autoriteitpersoonsgegevens.nl/",
  );
  await expect(page.getByTestId("consent-text")).toContainText("I agree that OpenFoodAlerts stores");
  await expect(page.locator("main")).toContainText("No cookies");
  expect(await context.cookies()).toEqual([]);
});

test("colofon lists the BW 3:15d fields (values from lib/legal.ts or a placeholder)", async ({
  page,
}) => {
  await page.goto("/nl/colofon");
  const colofon = page.getByTestId("colofon");
  for (const label of ["Handelsnaam", "Adres", "E-mail", "KvK-nummer", "Btw-identificatienummer"]) {
    await expect(colofon.locator("dt", { hasText: label })).toBeVisible();
  }
  await expect(colofon).toContainText("OpenFoodAlerts");
});

test("the language switch offers zh on legal pages and only English on /data", async ({ page }) => {
  await page.goto("/en/privacy");
  const switcher = page.getByRole("navigation", { name: "Language" });
  await expect(switcher.getByRole("link", { name: "中文" })).toHaveAttribute("href", "/zh/privacy");
  await page.goto("/en/data");
  await expect(page.getByRole("navigation", { name: "Language" }).getByRole("link")).toHaveCount(0);
});

test("/data shows sources with their attribution texts and the taxonomy merge table", async ({
  page,
}) => {
  const response = await page.goto("/en/data");
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Data and methods");
  for (const text of ATTRIBUTIONS) await expect(page.locator("main")).toContainText(text);
  await expect(page.getByRole("heading", { name: "Coverage" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scope and exclusion rules" })).toBeVisible();

  await expect(page.getByTestId("taxonomy-status")).toContainText("draft — not frozen");
  const table = page.getByTestId("taxonomy-table");
  // 30 RASFF categories, one row each; three of them form "GMO / novel food".
  await expect(table.locator("tbody tr")).toHaveCount(30);
  const gmo = table.locator("tbody", { has: page.locator("th", { hasText: "GMO / novel food" }) });
  await expect(gmo.locator("tr")).toHaveCount(3);
  await expect(gmo).toContainText("genetically modified");
  await expect(table.locator("tbody").last().locator("th")).toContainText("other");

  // The evaluation link goes to the site, repository files to the repository.
  await expect(page.getByRole("link", { name: "evaluation", exact: true })).toHaveAttribute(
    "href",
    "/en/evaluation",
  );
  await expect(page.getByRole("link", { name: "db/seed/taxonomy/v1-draft.csv" }).first()).toHaveAttribute(
    "href",
    /\/blob\/main\/db\/seed\/taxonomy\/v1-draft\.csv$/,
  );
  await expectNoAxeViolations(page);
});

test("/data is English only: nl and zh redirect to /en/data", async ({ page }) => {
  for (const locale of ["nl", "zh"]) {
    await page.goto(`/${locale}/data`);
    await expect(page).toHaveURL(/\/en\/data$/);
  }
});

test("pages outside the Chinese module still 404 under /zh", async ({ page }) => {
  const response = await page.goto("/zh/dashboard");
  expect(response?.status()).toBe(404);
});
