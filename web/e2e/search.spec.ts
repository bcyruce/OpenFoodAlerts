// Smoke tests for /search and /api/search, against the fixtures loaded by `make web-fixtures`
// (openFDA, RASFF and NVWA snapshots plus e2e/fixtures/rasff/news_synthetic.json, a
// synthetic RASFF News record). Counts are compared relatively where new fixtures could
// change them.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const results = (page: Page) => page.getByTestId("result");
const ofSource = (page: Page, source: string) =>
  page.locator(`[data-testid="result"][data-source="${source}"]`);

async function shownCount(page: Page): Promise<number> {
  const text = (await page.getByTestId("result-count").textContent()) ?? "";
  return Number(text.match(/\d+/)?.[0] ?? 0);
}

test("searches all Sources and narrows the results with a keyboard-operated filter", async ({
  page,
}) => {
  await page.goto("/en/search");
  const box = page.getByLabel("Search terms");
  await box.fill("salmonella");
  await box.press("Enter");
  // The form's empty fields are dropped: one short, shareable URL per search.
  await expect(page).toHaveURL(/\/en\/search\?q=salmonella$/);
  for (const source of ["rasff", "nvwa", "openfda"]) {
    await expect(ofSource(page, source).first()).toBeVisible();
  }
  const before = await shownCount(page);
  await expect(results(page)).toHaveCount(before);

  const rasff = page.getByTestId("facet-source").getByRole("checkbox", { name: /^RASFF \(\d+\)$/ });
  await rasff.focus();
  await page.keyboard.press("Space");
  await expect(rasff).toBeChecked();
  await page.getByRole("button", { name: "Apply filters" }).focus();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/en\/search\?q=salmonella&source=rasff$/);
  const after = await shownCount(page);
  expect(after).toBeGreaterThan(0);
  expect(after).toBeLessThan(before);
  await expect(results(page)).toHaveCount(after);
  await expect(ofSource(page, "rasff")).toHaveCount(after);
  await expect(page.getByTestId("facet-source").getByRole("checkbox", { name: /^RASFF/ })).toBeChecked();
  // Other Sources stay selectable, with their counts for this query.
  await expect(
    page.getByTestId("facet-source").getByRole("checkbox", { name: /^NVWA \(\d+\)$/ }),
  ).not.toBeChecked();
  await expect(
    ofSource(page, "rasff").getByRole("link", { name: /Salmonella Anatum/ }),
  ).toHaveAttribute("href", "/en/n/rasff/2026.9181");
});

test("filters by Hazard category from the URL and badges official values", async ({ page }) => {
  await page.goto("/en/search?hazard=21795");
  await expect(
    page.getByTestId("facet-hazard").getByRole("checkbox", { name: /^pesticide residues/ }),
  ).toBeChecked();
  const count = await shownCount(page);
  expect(count).toBeGreaterThan(0);
  await expect(
    results(page).locator('[data-provenance="official"]', { hasText: "pesticide residues" }),
  ).toHaveCount(Math.min(count, 20));
});

test("shows NVWA as not graded and finds RASFF News", async ({ page }) => {
  await page.goto("/en/search?q=cheese");
  await expect(results(page).filter({ hasText: "2026.9901" })).toContainText("RASFF · news");
  await page.goto("/en/search?q=korianderzaad");
  const nvwa = ofSource(page, "nvwa").first();
  await expect(nvwa).toContainText("Not graded");
  await nvwa.getByRole("link").click();
  await expect(page).toHaveURL(/\/en\/n\/nvwa\/actueel\/nieuws\/2026\/10\/13\//);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Veiligheidswaarschuwing Cook korianderzaad gemalen",
  );
});

test("keeps the official-only switch in the URL", async ({ page }) => {
  await page.goto("/en/search?q=salmonella");
  await page.getByLabel("Official classifications only").check();
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/official_only=1/);
  await expect(page.getByLabel("Official classifications only")).toBeChecked();
});

test("pages through the results", async ({ page }) => {
  await page.goto("/en/search");
  await expect(page.getByText(/^Page 1 of \d+$/)).toBeVisible();
  await expect(results(page)).toHaveCount(20);
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Next page" }).click();
  await expect(page).toHaveURL(/\/en\/search\?page=2$/);
  await expect(page.getByText(/^Page 2 of \d+$/)).toBeVisible();
});

test("is not indexed and has a Dutch interface", async ({ page }) => {
  await page.goto("/nl/search?q=salmonella");
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Meldingen zoeken");
  await expect(page.getByTestId("result-count")).toHaveText(/\d+ meldingen gevonden/);
  await expect(ofSource(page, "nvwa").first()).toContainText("Niet ingedeeld");
});

test("/api/search returns results and facet counts as JSON", async ({ request }) => {
  const response = await request.get("/api/search?q=salmonella&source[]=rasff");
  expect(response.status()).toBe(200);
  expect(response.headers()["x-robots-tag"]).toBe("noindex");
  const body = await response.json();
  expect(body.filters.sources).toEqual(["rasff"]);
  expect(body.total).toBeGreaterThan(0);
  for (const r of body.results) {
    expect(r.source).toBe("rasff");
    expect(r.path).toMatch(/^\/en\/n\/rasff\//);
  }
  const nvwa = body.facets.source.find((f: { value: string }) => f.value === "nvwa");
  expect(nvwa).toMatchObject({ label: "NVWA", selected: false });
  expect(nvwa.count).toBeGreaterThan(0);
  expect(body.facets).toHaveProperty("hazard");
  expect(body.facets).toHaveProperty("country");
});

test("search page has no WCAG 2 A/AA violations (axe)", async ({ page }) => {
  await page.goto("/en/search?q=salmonella");
  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(scan.violations).toEqual([]);
});
