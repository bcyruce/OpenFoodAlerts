// Smoke tests for the home page, the site header and footer, the ad box rule (spec §11.3)
// and /sitemap.xml + /robots.txt, against the fixtures loaded by `make web-fixtures`.
// The fixtures' publication dates slide out of "last 7 days" over time, so the recent
// list is checked for its structure, not for particular Notifications.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const AD_LABEL = "Advertentie / 广告 — van de maker van deze site";
const UTM = /^https:\/\/[^?]+\?utm_source=openfoodalerts\.nl&utm_medium=(footer|home_box)&utm_campaign=v1$/;

test("home shows the value proposition, last 7 days, charts and the subscription entry", async ({
  page,
}) => {
  const response = await page.goto("/en");
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page).toHaveTitle("OpenFoodAlerts");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Official food-safety notifications from RASFF, NVWA and openFDA",
  );

  const recent = page.getByTestId("home-recent");
  await expect(recent.getByRole("heading", { name: "Last 7 days" })).toBeVisible();
  for (const [code, label] of [
    ["rasff", "RASFF"],
    ["nvwa", "NVWA"],
    ["openfda", "openFDA"],
  ]) {
    const block = page.getByTestId(`recent-${code}`);
    await expect(block.getByRole("heading", { name: label })).toBeVisible();
    const items = block.getByTestId("recent-item");
    if ((await items.count()) === 0) {
      await expect(block).toContainText("No notifications from this source in the last 7 days.");
    } else {
      await expect(items.first().getByRole("link")).toHaveAttribute("href", new RegExp(`^/en/n/${code}/`));
      await expect(block.getByRole("link", { name: /in search$/ })).toHaveAttribute(
        "href",
        new RegExp(`^/en/search\\?source=${code}&from=\\d{4}-\\d{2}-\\d{2}$`),
      );
    }
  }

  const charts = page.getByTestId("home-charts");
  await expect(page.getByTestId("home-chart-timeseries").locator("svg")).toBeVisible();
  await page.getByTestId("home-table-timeseries").locator("summary").click();
  await expect(page.getByTestId("home-table-timeseries").locator("tfoot")).toContainText("Total");
  // The RASFF fixtures are recent enough to have official hazard categories in 12 months.
  await expect(page.getByTestId("home-chart-top").locator("svg")).toBeVisible();
  await expect(charts.getByRole("link", { name: /Open the dashboard/ })).toHaveAttribute(
    "href",
    "/en/dashboard",
  );

  await expect(
    page.getByTestId("home-subscribe").getByRole("link", { name: "Subscribe to a daily Digest by email" }),
  ).toHaveAttribute("href", "/en/alerts");
});

test("home is indexable with hreflang alternates, and Dutch under /nl", async ({ page }) => {
  await page.goto("/nl");
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/nl$/);
  await expect(page.locator('link[rel="alternate"][hreflang="en"]')).toHaveAttribute("href", /\/en$/);
  await expect(page.getByRole("heading", { name: "Afgelopen 7 dagen" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Hoofdmenu" }).getByRole("link", { name: "Zoeken" }))
    .toHaveAttribute("href", "/nl/search");
});

test("the ad box is at the bottom of home, labelled, separate and with UTM", async ({ page }) => {
  await page.goto("/en");
  const ad = page.getByTestId("ad-box");
  await expect(ad).toHaveCount(1);
  await expect(page.getByRole("complementary", { name: AD_LABEL })).toBeVisible();
  const link = ad.getByRole("link");
  await expect(link).toHaveAttribute("rel", /sponsored/);
  expect(await link.getAttribute("href")).toMatch(UTM);
  expect(await link.getAttribute("href")).toContain("utm_medium=home_box");
  // Last element of the page content.
  await expect(page.locator("main > :last-child")).toHaveAttribute("data-testid", "ad-box");
  await page.goto("/nl");
  await expect(page.getByTestId("ad-box")).toHaveCount(1);
});

// Every other existing page, and the ones still to come (tickets 25 and 27). Until those
// exist their URLs fall through to app/global-not-found.tsx, which has no site layout.
const PLANNED = ["/en/evaluation", "/en/data", "/en/about", "/nl/privacy", "/en/disclaimer", "/en/colofon"];
for (const path of [
  "/en/dashboard",
  "/nl/dashboard?months=all",
  "/en/search",
  "/en/search?q=salmonella",
  "/en/n/openfda/H-0015-2027",
  "/nl/n/openfda/H-0015-2027",
  "/en/alerts",
  "/zh/alerts",
  "/en/alerts/confirm",
  "/en/n/openfda/H-9999-2027",
  ...PLANNED,
]) {
  test(`no ad box on ${path}`, async ({ page }) => {
    await page.goto(path, { waitUntil: "networkidle" });
    if (!PLANNED.includes(path)) await expect(page.getByTestId("site-footer")).toBeVisible();
    await expect(page.getByTestId("ad-box")).toHaveCount(0);
    await expect(page.getByText(AD_LABEL)).toHaveCount(0);
  });
}

test("the footer has the attribution with UTM, the legal links and the disclaimer", async ({
  page,
}) => {
  await page.goto("/en/search");
  const footer = page.getByTestId("site-footer");
  const builtBy = page.getByTestId("footer-built-by");
  await expect(builtBy).toHaveText(/^Built by .+, founder of SnelVink$/);
  const href = await builtBy.getByRole("link", { name: "SnelVink" }).getAttribute("href");
  expect(href).toMatch(UTM);
  expect(href).toContain("utm_medium=footer");
  await expect(page.getByTestId("footer-disclaimer")).toContainText("not an official source");
  await expect(page.getByTestId("footer-disclaimer")).toContainText("AI classifications may be wrong");
  await expect(page.getByTestId("footer-sources")).toContainText("RASFF");
  const links = footer.getByRole("navigation", { name: "About this site" });
  for (const [name, target] of [
    ["Data and licences", "/en/data"],
    ["About", "/en/about"],
    ["Privacy", "/en/privacy"],
    ["Disclaimer", "/en/disclaimer"],
    ["Colofon", "/en/colofon"],
  ]) {
    await expect(links.getByRole("link", { name, exact: true })).toHaveAttribute("href", target);
  }
});

test("the footer is in Chinese on zh pages", async ({ page }) => {
  await page.goto("/zh/alerts");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
  await expect(page.getByTestId("footer-built-by")).toContainText("SnelVink 创始人");
  await expect(page.getByTestId("footer-disclaimer")).toContainText("本站非官方来源");
  await expect(page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "订阅" }))
    .toHaveAttribute("aria-current", "page");
});

test("the header navigation marks the current section and is keyboard-reachable", async ({ page }) => {
  await page.goto("/en/dashboard");
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const [name, href] of [
    ["Home", "/en"],
    ["Dashboard", "/en/dashboard"],
    ["Search", "/en/search"],
    ["Subscribe", "/en/alerts"],
  ]) {
    await expect(nav.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
  }
  await expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Tab"); // skip link
  await page.keyboard.press("Tab"); // site name
  await page.keyboard.press("Tab");
  await expect(nav.getByRole("link", { name: "Home" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/en$/);
});

test("the language switch keeps search and dashboard filters", async ({ page }) => {
  await page.goto("/en/search?q=salmonella&source=rasff");
  await page.getByRole("link", { name: "Nederlands" }).click();
  await expect(page).toHaveURL(/\/nl\/search\?q=salmonella&source=rasff$/);

  // The dashboard rewrites the address bar on the client (history.replaceState).
  await page.goto("/en/dashboard?months=all");
  await page.getByTestId("dashboard-filters").getByRole("checkbox", { name: "NVWA" }).uncheck();
  await expect(page).toHaveURL(/source=/);
  const filtered = new URL(page.url()).search;
  await page.getByRole("link", { name: "Nederlands" }).click();
  await expect(page).toHaveURL(/\/nl\/dashboard\?/);
  const switched = new URL(page.url());
  expect(switched.pathname).toBe("/nl/dashboard");
  expect(switched.search).toBe(filtered);
});

test("home has no WCAG 2 A/AA violations (axe)", async ({ page }) => {
  await page.goto("/en");
  await page.getByTestId("home-chart-timeseries").locator("svg").waitFor();
  for (const summary of await page.locator("details summary").all()) await summary.click();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});

test("/sitemap.xml lists home, dashboard, legal and Notification pages with hreflang", async ({
  request,
}) => {
  const response = await request.get("/sitemap.xml");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("xml");
  const xml = await response.text();
  const site = "https://openfoodalerts.nl";
  for (const loc of [`${site}/en`, `${site}/nl/dashboard`, `${site}/en/data`, `${site}/zh/privacy`]) {
    expect(xml).toContain(`<loc>${loc}</loc>`);
  }
  expect(xml).toContain(`<loc>${site}/en/n/openfda/H-0015-2027</loc>`);
  expect(xml).toContain(`hreflang="nl" href="${site}/nl/n/openfda/H-0015-2027"`);
  // Non-food and pending Notifications, search and subscription pages are not listed.
  expect(xml).not.toContain("Z-9001-2027");
  expect(xml).not.toContain("Z-9002-2027");
  expect(xml).not.toMatch(/<loc>[^<]*\/(search|alerts)/);
});

test("/robots.txt allows crawling, keeps /api/ out and points to the sitemap", async ({ request }) => {
  const response = await request.get("/robots.txt");
  expect(response.status()).toBe(200);
  const text = await response.text();
  expect(text).toContain("Disallow: /api/");
  expect(text).toContain("Allow: /");
  expect(text).toContain("Sitemap: https://openfoodalerts.nl/sitemap.xml");
});

test("search and subscription pages stay noindex", async ({ page }) => {
  for (const path of ["/en/search", "/en/alerts", "/zh/alerts", "/en/alerts/confirm"]) {
    await page.goto(path);
    await expect(page.locator('meta[name="robots"]'), path).toHaveAttribute("content", /noindex/);
  }
});
