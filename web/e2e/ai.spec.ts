// Smoke tests for AI classifications in the UI (ticket 24, spec §9 AI badge, §6.5 review,
// S3 "official only"). AI rows come from `make web-fixtures`: T1 from the fake model
// (`ofa classify --model fake`), T2/T3/T4/T5/T6 and one approved review from
// e2e/fixtures/ai/classifications.json. latest.json has no test runs yet, so every badge
// must say "not yet evaluated" rather than quote a number.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const CORIANDER = "/en/n/nvwa/actueel/nieuws/2026/10/13/veiligheidswaarschuwing-cook-korianderzaad-gemalen";
const POKEBOWL = "/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen";
const PATHOGENS = 21801;

const aiValue = (page: Page, task: string) =>
  page.getByTestId("ai-fields").locator(`[data-testid="ai-value"][data-task="${task}"]`);

async function shownCount(page: Page): Promise<number> {
  const text = (await page.getByTestId("result-count").textContent()) ?? "";
  return Number(text.replace(/[^\d]/g, ""));
}

test("the detail page shows T1–T4 and the T6 summary badged, never T5, NVWA not graded", async ({
  page,
}) => {
  await page.goto(CORIANDER);
  await expect(page.getByTestId("official-fields")).toContainText("Not graded");
  await expect(aiValue(page, "hazard_category")).toContainText("pathogenic micro-organisms");
  await expect(aiValue(page, "hazard")).toContainText("Salmonella");
  await expect(aiValue(page, "product_category")).toContainText("herbs and spices");
  await expect(aiValue(page, "origin_country")).toContainText("Not stated in the source text");
  // T5 (Product type) is internal (spec §6.1).
  await expect(page.getByTestId("ai-fields")).not.toContainText("Product type");
  await expect(page.getByTestId("ai-fields").locator('[data-task="product_type"]')).toHaveCount(0);
  const summary = page.getByTestId("ai-summary");
  await expect(summary.getByRole("heading")).toHaveText("Summary (AI-generated)");
  await expect(summary).toContainText("Ground coriander seed from Cook may contain Salmonella.");
  // Every AI value has a badge.
  await expect(page.getByTestId("ai-fields").getByTestId("ai-badge")).toHaveCount(5);

  // Official and AI areas differ in border style, not only colour.
  const style = (testId: string) =>
    page.getByTestId(testId).evaluate((el) => getComputedStyle(el).borderTopStyle);
  expect(await style("official-fields")).toBe("solid");
  expect(await style("ai-fields")).toBe("dashed");
});

test("the summary follows the page language", async ({ page }) => {
  await page.goto(CORIANDER.replace("/en/", "/nl/"));
  const summary = page.getByTestId("ai-summary");
  await expect(summary.getByRole("heading")).toHaveText("Samenvatting (Door AI gemaakt)");
  await expect(summary).toContainText("Gemalen korianderzaad van Cook kan Salmonella bevatten.");
  await expect(aiValue(page, "origin_country")).toContainText("Niet vermeld in de brontekst");
});

test("the badge explains itself on keyboard focus and hover, and closes with Escape", async ({
  page,
}) => {
  await page.goto(CORIANDER);
  const badge = aiValue(page, "hazard_category").getByTestId("ai-badge");
  const button = badge.getByRole("button", { name: "AI classification" });
  const popup = badge.getByTestId("ai-badge-popup");
  await expect(popup).toBeHidden();
  await expect(button).toHaveAccessibleDescription(
    /^Classified by fake on .+ 2026, prompt v1\. Not yet evaluated on the test set\. The official text prevails\.$/,
  );

  await button.focus();
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("Not yet evaluated on the test set.");
  await expect(popup.getByRole("link", { name: "Official source" })).toHaveAttribute(
    "href",
    /^https:\/\/www\.nvwa\.nl\/actueel\/nieuws\/2026\/10\/13\//,
  );
  await expect(popup.getByRole("link", { name: "How the AI is evaluated" })).toHaveAttribute(
    "href",
    "/en/evaluation",
  );
  // Tab moves into the popup's links; it stays open.
  await page.keyboard.press("Tab");
  await expect(popup.getByRole("link", { name: "Official source" })).toBeFocused();
  await expect(popup).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();

  await page.getByRole("heading", { level: 1 }).focus();
  await button.hover();
  await expect(popup).toBeVisible();
});

test("a reviewed value is badged as reviewed by a person", async ({ page }) => {
  await page.goto(POKEBOWL);
  const badge = aiValue(page, "hazard_category").getByTestId("ai-badge");
  await expect(badge).toHaveAttribute("data-reviewed", "true");
  await expect(badge.getByRole("button", { name: "Reviewed by a person" })).toHaveAccessibleDescription(
    /^Reviewed by a person\. Classified by fake on /,
  );
  await expect(aiValue(page, "hazard_category")).toContainText("allergens");
});

test("search: AI values are badged and the official-only switch changes the results", async ({
  page,
}) => {
  await page.goto(`/en/search?hazard=${PATHOGENS}`);
  const withAi = await shownCount(page);
  const results = page.getByTestId("results");
  await expect(results.locator('[data-source="nvwa"]').first()).toBeVisible();
  const aiChip = results.locator('[data-provenance="ai"]', { hasText: "pathogenic micro-organisms" });
  await expect(aiChip.first().getByRole("button", { name: "AI classification" })).toBeVisible();
  const facet = page.getByTestId("facet-hazard").getByRole("checkbox", { name: /^pathogenic/ });
  const facetWithAi = await facet.locator("xpath=..").textContent();

  // Switch it on with the keyboard and apply.
  await page.getByLabel("Official classifications only").focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(new RegExp(`hazard=${PATHOGENS}.*official_only=1`));
  const officialOnly = await shownCount(page);
  expect(officialOnly).toBeLessThan(withAi);
  await expect(results.locator('[data-provenance="ai"]')).toHaveCount(0);
  await expect(results.locator('[data-source="nvwa"]')).toHaveCount(0);
  expect(await facet.locator("xpath=..").textContent()).not.toBe(facetWithAi);
});

test("dashboard: AI numbers are marked and the official-only switch removes them", async ({
  page,
}) => {
  await page.goto("/en/dashboard?months=all");
  await expect(page.getByTestId("ai-note")).toBeVisible();
  await expect(page.getByTestId("classified-ai-nvwa")).toContainText("from AI classifications");
  const table = page.getByTestId("table-top-hazard-nvwa");
  await table.locator("summary").click();
  await expect(table.locator("thead")).toContainText("Of which AI");
  await expect(table.getByTestId("ai-mark").first()).toBeVisible();

  await page.getByRole("checkbox", { name: "Official classifications only" }).check();
  await expect(page).toHaveURL(/official_only=1/);
  await expect(page.getByTestId("dashboard-status")).toHaveText("Charts updated.");
  await expect(page.getByTestId("ai-note")).toHaveCount(0);
  await expect(page.getByTestId("table-top-hazard-nvwa")).toHaveCount(0);
  await expect(page.getByTestId("source-nvwa")).toContainText("No values");
});

test("an open badge never widens the page, on a phone or a narrow desktop", async ({ page }) => {
  for (const width of [360, 800]) {
    await page.setViewportSize({ width, height: 740 });
    for (const path of [CORIANDER, `/en/search?hazard=${PATHOGENS}`]) {
      await page.goto(path);
      for (const button of await page.getByTestId("ai-badge").getByRole("button").all()) {
        await button.focus();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, `${path} at ${width}px`).toBeLessThanOrEqual(0);
      }
    }
  }
});

for (const path of [CORIANDER, POKEBOWL, `/en/search?hazard=${PATHOGENS}`]) {
  test(`${path} with AI badges has no WCAG 2 A/AA violations (axe)`, async ({ page }) => {
    await page.goto(path);
    // Open one popup so its contents are checked too.
    await page.getByTestId("ai-badge").first().getByRole("button").focus();
    const scan = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(scan.violations).toEqual([]);
  });
}
