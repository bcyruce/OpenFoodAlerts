// Smoke tests for /en/evaluation (ticket 25). The real page is built from the committed
// eval/results/latest.json (no Labels yet: empty state). The full layout is checked on
// /en/evaluation/example, built from the SYNTHETIC example.json because `make smoke` sets
// OFA_EVAL_EXAMPLE=1; deployments never do, so there that route is a 404.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectNoAxeViolations(page: Page) {
  const scan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(scan.violations).toEqual([]);
}

async function openAllDetails(page: Page) {
  await page.locator("main details").evaluateAll((all) => all.forEach((d) => d.setAttribute("open", "")));
}

test.describe("the real page (eval/results/latest.json)", () => {
  test("explains that labelling is in progress and links the method", async ({ page }) => {
    const response = await page.goto("/en/evaluation");
    expect(response?.status()).toBe(200);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Evaluation");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/en\/evaluation$/);
    await expect(page.locator("article")).toHaveAttribute("data-synthetic", "false");
    await expect(page.getByTestId("synthetic-banner")).toHaveCount(0);
    await expect(page.getByText("synthetic", { exact: true })).toHaveCount(0);

    const empty = page.getByTestId("evaluation-empty");
    await expect(empty.getByRole("heading")).toHaveText("No results yet: labelling is in progress");
    await expect(empty).toContainText("baseline-keywords (kw1) on test");
    await expect(empty.getByRole("link", { name: "Method" })).toHaveAttribute("href", "#method");
    await expect(page.locator("#method")).toBeVisible();
    // No metrics while nothing is labelled.
    await expect(page.locator('[data-testid^="split-"]')).toHaveCount(0);
    const testRow = page.getByTestId("label-status").locator("tbody tr").first();
    await expect(testRow.locator("th")).toHaveText("test (frozen)");
    await expect(testRow.locator("td")).toHaveText(["200", "0"]);

    await expect(page.getByTestId("agreement")).toContainText("Not measured yet");
    await expect(page.getByTestId("noise-audit-agreement")).toHaveText("—");
    await expect(page.getByTestId("limitations").locator("li")).toHaveCount(7);
    await expect(page.getByTestId("references")).toContainText("Food Control");
    await expect(page.getByTestId("references")).toContainText("10.1108/BFJ-10-2024-1072");
    await expect(page.getByTestId("references")).toContainText("10.5281/zenodo.4322555");
  });

  test("links the eval set, the guidelines and the one-command reproduction", async ({ page }) => {
    await page.goto("/en/evaluation");
    const reproduce = page.getByTestId("reproduce");
    for (const file of ["eval/items.csv", "eval/labels.csv", "eval/results/latest.json"]) {
      await expect(reproduce.getByRole("link", { name: file, exact: true })).toHaveAttribute(
        "href",
        new RegExp(`/blob/main/${file.replace(/\./g, "\\.")}$`),
      );
    }
    await expect(reproduce.getByRole("link", { name: "annotation guidelines" })).toHaveAttribute(
      "href",
      /\/blob\/main\/docs\/annotation_guidelines\.md$/,
    );
    await expect(page.getByTestId("reproduce-command")).toContainText("make eval SPLIT=test");
  });

  test("passes axe, has no ad box and is English only", async ({ page }) => {
    await page.goto("/en/evaluation", { waitUntil: "networkidle" });
    await expect(page.getByTestId("site-footer")).toBeVisible();
    await expect(page.getByTestId("ad-box")).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Language" }).getByRole("link")).toHaveCount(0);
    await expectNoAxeViolations(page);
    for (const locale of ["nl", "zh"]) {
      await page.goto(`/${locale}/evaluation`);
      await expect(page).toHaveURL(/\/en\/evaluation$/);
    }
  });

  test("the main navigation links it, from nl too", async ({ page }) => {
    await page.goto("/en/evaluation");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Evaluation" })).toHaveAttribute("aria-current", "page");
    await page.goto("/nl");
    const link = page.getByRole("navigation", { name: "Hoofdmenu" }).getByRole("link", { name: "Evaluatie" });
    await expect(link).toHaveAttribute("href", "/en/evaluation");
    await expect(link).toHaveAttribute("hreflang", "en");
  });

  test("is in the sitemap; the example page is not", async ({ request }) => {
    const sitemap = await (await request.get("/sitemap.xml")).text();
    expect(sitemap).toMatch(/<loc>[^<]*\/en\/evaluation<\/loc>/);
    expect(sitemap).not.toContain("/evaluation/example");
  });
});

test.describe("the synthetic example (test builds only)", () => {
  test("is marked synthetic everywhere and not indexed", async ({ page }) => {
    const response = await page.goto("/en/evaluation/example");
    expect(response?.status()).toBe(200);
    await expect(page.locator("article")).toHaveAttribute("data-synthetic", "true");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("synthetic example");
    await expect(page.getByTestId("synthetic-banner")).toContainText("Synthetic example — not real results");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
    // Every section with numbers carries the tag.
    for (const id of ["split-test", "split-dev", "agreement", "noise-audit"]) {
      await expect(page.getByTestId(id).getByRole("heading").first()).toContainText("synthetic");
    }
    await expect(page.getByTestId("evaluation-empty")).toHaveCount(0);
  });

  test("shows the model comparison with baselines and the metrics per source", async ({ page }) => {
    await page.goto("/en/evaluation/example");
    const comparison = page.getByTestId("comparison-test");
    await expect(comparison.locator("tbody tr")).toHaveCount(3);
    await expect(comparison.locator("tbody tr").nth(0)).toContainText("synthetic-model (v0)model196");
    await expect(comparison.locator("tbody tr").nth(0)).toContainText("0.65 (0.53–0.70)");
    await expect(comparison.locator("tbody tr").nth(1)).toContainText("baseline-keywords");

    const t1 = page.getByTestId("run-test-hazard_category-synthetic-model-v0");
    const rows = t1.locator("table").first().locator("tbody th");
    await expect(rows).toHaveText(["All sources", "RASFF (subject only)", "NVWA", "openFDA"]);
    await expect(t1.locator("table").first().locator("tbody tr").nth(2)).toContainText("0.84 (0.75–0.92)");

    const t3 = page.getByTestId("run-test-hazard-synthetic-model-v0");
    await expect(t3.locator("thead")).toContainText("Exact match");
    await expect(t3.locator("tbody tr").first()).toContainText("0.47");
  });

  test("draws the coverage–accuracy curve next to its data table", async ({ page }) => {
    await page.goto("/en/evaluation/example", { waitUntil: "networkidle" });
    const coverage = page.getByTestId("run-test-hazard_category-synthetic-model-v0-coverage");
    await expect(coverage).toContainText("no low-confidence threshold chosen yet");
    const chart = coverage.getByTestId("run-test-hazard_category-synthetic-model-v0-coverage-chart");
    await expect(chart).toHaveAttribute("role", "img");
    await expect(chart).toHaveAttribute("aria-label", /Coverage and accuracy/);
    await expect(chart.locator("svg").first()).toBeVisible();
    const table = coverage.getByTestId("run-test-hazard_category-synthetic-model-v0-coverage-table");
    // Keyboard: the disclosure opens with Enter.
    await table.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(table.locator("tbody tr")).toHaveCount(3);
    await expect(table.locator("tbody tr").nth(1)).toContainText("High + medium77.0%, 83.4% (151)");
  });

  test("has the confusion matrix, κ and the noise audit", async ({ page }) => {
    await page.goto("/en/evaluation/example");
    const confusion = page.getByTestId("run-test-hazard_category-synthetic-model-v0-confusion");
    await confusion.locator("summary").click();
    await expect(confusion.locator("thead th").last()).toHaveText("abstain");
    await expect(confusion.locator("tbody tr")).toHaveCount(26);
    await expect(page.getByTestId("agreement")).toContainText("κ = 0.87 on 57 items");
    await expect(page.getByTestId("noise-audit-agreement")).toHaveText("91.7%");
  });

  test("passes axe with every table open and has no ad box", async ({ page }) => {
    await page.goto("/en/evaluation/example", { waitUntil: "networkidle" });
    await expect(page.getByTestId("ad-box")).toHaveCount(0);
    await openAllDetails(page);
    await expectNoAxeViolations(page);
  });
});
