// Subscription flow (ticket 28): form → confirmation email (outbox test transport) →
// confirm page. Each test uses a fresh address, so reruns against one database work.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { messagesTo, uniqueEmail, waitForEmail } from "./outbox";

const CONSENT_VERSION = "2026-10-25";

function confirmPath(text: string): string {
  const match = text.match(/https?:\/\/[^/\s]+(\/(?:en|nl|zh)\/alerts\/confirm#token=[A-Za-z0-9_-]{43})/);
  if (!match) throw new Error(`no confirm link in:\n${text}`);
  return match[1];
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test("subscribe, receive the confirmation email and confirm", async ({ page }) => {
  const email = uniqueEmail("flow");
  const response = await page.goto("/en/alerts");
  expect(response?.status()).toBe(200);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Subscribe to email updates");

  await page.getByRole("textbox", { name: "Email address" }).fill(email);
  await page.getByRole("radio", { name: "Nederlands" }).check();
  await page.getByRole("checkbox", { name: /^openFDA —/ }).uncheck();
  await expect(page.getByRole("checkbox", { name: "Instant email for openFDA" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "Instant email for NVWA" }).check();
  await page.locator("summary", { hasText: "Hazard categories" }).click();
  await page.getByRole("checkbox", { name: "allergens" }).check();
  await expect(page.locator("summary", { hasText: "Hazard categories" })).toContainText("1 selected");
  await expect(
    page.getByRole("checkbox", { name: "Also include notifications without a classification" }),
  ).toBeChecked();
  await page.getByRole("checkbox", { name: /^I agree that OpenFoodAlerts stores/ }).check();
  await page.getByRole("button", { name: "Subscribe" }).click();

  await expect(page.getByRole("status")).toContainText("Check your inbox");
  await expect(page.getByRole("status")).toContainText(email);

  const message = await waitForEmail(email);
  expect(message.subject).toBe("Bevestig uw abonnement op OpenFoodAlerts");
  expect(message.text).toContain("Bronnen: NVWA, RASFF");
  expect(message.text).toContain("Gevarencategorieën: 1 geselecteerd");
  expect(message.text).toContain("Instant e-mail: NVWA");
  expect(message.html).toContain('<html lang="nl">');

  const link = confirmPath(message.text);
  await page.goto(link);
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await page.getByRole("button", { name: "Abonnement bevestigen" }).click();
  await expect(page.getByRole("status")).toContainText("Abonnement bevestigd");
  // The token is removed from the address bar once used.
  await expect(page).toHaveURL(/\/nl\/alerts\/confirm$/);

  // The link works only once (opened afresh, as from the email).
  await page.goto("about:blank");
  await page.goto(link);
  await page.getByRole("button", { name: "Abonnement bevestigen" }).click();
  await expect(page.getByText("Deze bevestigingslink is ongeldig of al gebruikt.")).toBeVisible();

  // Subscribing again with an active address sends nothing, and says the same as before.
  await page.goto("/en/alerts");
  await page.getByRole("textbox", { name: "Email address" }).fill(email);
  await page.getByRole("checkbox", { name: /^I agree that OpenFoodAlerts stores/ }).check();
  await page.getByRole("button", { name: "Subscribe" }).click();
  await expect(page.getByRole("status")).toContainText("Check your inbox");
  await page.waitForTimeout(2000);
  expect(messagesTo(email)).toHaveLength(1);
});

test("Chinese subscriptions can only choose NVWA", async ({ page }) => {
  await page.goto("/zh/alerts");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("订阅邮件");
  await expect(page.getByRole("radio", { name: "中文" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /^NVWA —/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /^RASFF —/ })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: /^openFDA —/ })).toBeDisabled();
  await expect(page.getByTestId("zh-note")).toBeVisible();

  await page.getByRole("radio", { name: "English" }).check();
  await expect(page.getByRole("checkbox", { name: /^RASFF —/ })).toBeEnabled();
  await expect(page.getByRole("checkbox", { name: /^RASFF —/ })).toBeChecked();

  const email = uniqueEmail("zh");
  await page.getByRole("radio", { name: "中文" }).check();
  await page.getByRole("textbox", { name: "邮箱地址" }).fill(email);
  await page.getByRole("checkbox", { name: /^我同意/ }).check();
  await page.getByRole("button", { name: "订阅" }).click();
  await expect(page.getByRole("status")).toContainText("请查看您的邮箱");
  const message = await waitForEmail(email);
  expect(message.subject).toBe("请确认您的 OpenFoodAlerts 订阅");
  expect(message.text).toContain("来源：NVWA");
  expect(confirmPath(message.text)).toMatch(/^\/zh\/alerts\/confirm#/);
});

test("the API enforces the rules the form enforces", async ({ request }) => {
  const base = {
    email: uniqueEmail("api"),
    locale: "zh",
    filters: { sources: ["rasff"] },
    instant_sources: [],
    consent: true,
    consent_text_version: CONSENT_VERSION,
  };
  const zh = await request.post("/api/subscribe", { data: base });
  expect(zh.status()).toBe(400);
  expect((await zh.json()).fields).toEqual([{ field: "filters.sources", code: "zh_nvwa_only" }]);

  const instant = await request.post("/api/subscribe", {
    data: { ...base, locale: "en", filters: { sources: ["nvwa"] }, instant_sources: ["rasff"] },
  });
  expect(instant.status()).toBe(400);

  const form = await request.post("/api/subscribe", { form: { email: base.email } });
  expect(form.status()).toBe(415);

  const confirm = await request.post("/api/confirm", { data: { token: "x".repeat(43) } });
  expect(confirm.status()).toBe(400);
});

test("a filled honeypot looks accepted but sends nothing", async ({ request }) => {
  const email = uniqueEmail("bot");
  const response = await request.post("/api/subscribe", {
    data: {
      email,
      locale: "en",
      filters: {},
      consent: true,
      consent_text_version: CONSENT_VERSION,
      website: "https://spam.example",
    },
  });
  expect(response.status()).toBe(202);
  expect(await response.json()).toEqual({ status: "check_email" });
  await new Promise((resolve) => setTimeout(resolve, 2000));
  expect(messagesTo(email)).toEqual([]);
});

test("shows errors without sending when consent is missing", async ({ page }) => {
  await page.goto("/en/alerts");
  await page.getByRole("textbox", { name: "Email address" }).fill("not-an-email");
  await page.getByRole("button", { name: "Subscribe" }).click();
  await expect(page.getByText("Please correct the fields marked below.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Email address" })).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expect(page.getByText("Tick the consent box to subscribe.")).toBeVisible();
});

test("the confirm page explains a missing token", async ({ page }) => {
  await page.goto("/en/alerts/confirm");
  await expect(page.getByText(/needs the link from your confirmation email/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to the subscription form" })).toHaveAttribute(
    "href",
    "/en/alerts",
  );
});

test("filter groups open with the keyboard", async ({ page }) => {
  await page.goto("/en/alerts");
  const summary = page.locator("summary", { hasText: "Countries of origin" });
  await summary.focus();
  await page.keyboard.press("Enter");
  await page.getByLabel("Find a country").fill("nether");
  await expect(page.getByRole("checkbox", { name: "Netherlands", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "China", exact: true })).toBeHidden();
  await page.getByRole("checkbox", { name: "Netherlands", exact: true }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("checkbox", { name: "Netherlands", exact: true })).toBeChecked();
});

test("zh exists only for the subscription flow and the Chinese module", async ({ page }) => {
  expect((await page.goto("/zh"))?.status()).toBe(200);
  expect((await page.goto("/zh/n/openfda/H-0015-2027"))?.status()).toBe(404);
  await page.goto("/en/alerts");
  await expect(page.getByRole("link", { name: "中文" })).toHaveAttribute("href", "/zh/alerts");
  await page.goto("/en/n/openfda/H-0015-2027");
  await expect(page.getByRole("link", { name: "中文" })).toHaveCount(0);
});

for (const [path, openGroup] of [
  ["/en/alerts", "Hazard categories"],
  ["/zh/alerts", "危害类别"],
  ["/nl/alerts/confirm", null],
] as const) {
  test(`${path} has no WCAG 2 A/AA violations (axe)`, async ({ page }) => {
    await page.goto(path);
    if (openGroup) await page.locator("summary", { hasText: openGroup }).click();
    await expectNoAxeViolations(page);
  });
}
