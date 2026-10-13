// Manage link, unsubscribe and "delete my data" (ticket 29). Each test subscribes a fresh
// address through the API, confirms it and continues from the manage link that the
// confirmation answer returns (the same page Digest and Instant emails link to).
import AxeBuilder from "@axe-core/playwright";
import { expect, request as apiRequest, test, type APIRequestContext, type Page } from "@playwright/test";
import { messagesTo, uniqueEmail, waitForEmail } from "./outbox";

const CONSENT_VERSION = "2026-10-25";

function subscribeBody(email: string, locale = "en") {
  return {
    email,
    locale,
    filters: { sources: ["rasff", "nvwa"], hazard_categories: [], product_categories: [], origin_countries: [] },
    include_unclassified: true,
    instant_sources: ["nvwa"],
    consent: true,
    consent_text_version: CONSENT_VERSION,
  };
}

/** Subscribes and confirms `email`; returns the manage path from the confirmation answer. */
async function activeSubscription(request: APIRequestContext, email: string): Promise<string> {
  const subscribed = await request.post("/api/subscribe", { data: subscribeBody(email) });
  expect(subscribed.status()).toBe(202);
  const message = await waitForEmail(email);
  const token = message.text.match(/#token=([A-Za-z0-9_-]{43})/)![1];
  const confirmed = await request.post("/api/confirm", { data: { token } });
  expect(confirmed.status()).toBe(200);
  const { manage_path } = (await confirmed.json()) as { manage_path: string };
  expect(manage_path).toMatch(/^\/en\/alerts\/manage\/[A-Za-z0-9_-]{43}$/);
  return manage_path;
}

const tokenOf = (managePath: string) => managePath.split("/").pop()!;

async function subscriptionOf(request: APIRequestContext, managePath: string) {
  const response = await request.get(`/api/manage?token=${tokenOf(managePath)}`);
  return { status: response.status(), body: (await response.json()) as { subscription?: Record<string, unknown> } };
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
}

test("the confirmation page links to the manage page", async ({ page }) => {
  const email = uniqueEmail("confirm-manage");
  await page.request.post("/api/subscribe", { data: subscribeBody(email) });
  const message = await waitForEmail(email);
  await page.goto(message.text.match(/https?:\/\/[^/\s]+(\/en\/alerts\/confirm#token=[A-Za-z0-9_-]{43})/)![1]);
  await page.getByRole("button", { name: "Confirm subscription" }).click();
  await page.getByRole("link", { name: "manage your subscription" }).click();
  await expect(page).toHaveURL(/\/en\/alerts\/manage\/[A-Za-z0-9_-]{43}$/);
  await expect(page.getByTestId("subscription-status")).toContainText("Active");
});

test("manage: change the filters, then unsubscribe", async ({ page }) => {
  const email = uniqueEmail("manage");
  const managePath = await activeSubscription(page.request, email);

  const response = await page.goto(managePath);
  expect(response?.status()).toBe(200);
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Manage your subscription");
  // Only a masked address: the link may have been forwarded.
  await expect(page.getByText(/^Subscription for s\*\*\*@example\.com$/)).toBeVisible();
  await expect(page.getByText(email)).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "Instant email for NVWA" })).toBeChecked();
  await expectNoAxeViolations(page);

  await page.getByRole("checkbox", { name: /^RASFF —/ }).uncheck();
  await page.getByRole("radio", { name: "Nederlands" }).check();
  await page.locator("summary", { hasText: "Countries of origin" }).click();
  await page.getByRole("searchbox", { name: "Find a country" }).fill("Netherl");
  await page.getByRole("checkbox", { name: "Netherlands", exact: true }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Your changes have been saved.")).toBeVisible();

  const saved = await subscriptionOf(page.request, managePath);
  expect(saved.body.subscription).toMatchObject({
    status: "active",
    locale: "nl",
    filters: { sources: ["nvwa"], origin_countries: ["NL"] },
    instantSources: ["nvwa"],
  });
  await page.reload();
  await expect(page.getByRole("checkbox", { name: /^RASFF —/ })).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "Nederlands" })).toBeChecked();

  await page.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(page.getByText("You are unsubscribed. We will not send you any more emails.")).toBeVisible();
  await expect(page.getByTestId("subscription-status")).toContainText("Unsubscribed on");
  await expect(page.getByTestId("manage-form")).toHaveCount(0);
  expect((await subscriptionOf(page.request, managePath)).body.subscription?.status).toBe("unsubscribed");

  // Changing an unsubscribed Subscription is refused.
  const change = await page.request.post("/api/manage", {
    data: { token: tokenOf(managePath), ...subscribeBody(email), email: undefined },
  });
  expect(change.status()).toBe(409);
  await page.reload();
  await expect(page.getByTestId("subscription-status")).toContainText("Unsubscribed on");
});

test("manage rejects settings the subscription form would reject", async ({ request }) => {
  const managePath = await activeSubscription(request, uniqueEmail("manage-rules"));
  const token = tokenOf(managePath);
  const zh = await request.post("/api/manage", {
    data: { token, locale: "zh", filters: { sources: ["rasff", "nvwa"] }, instant_sources: [] },
  });
  expect(zh.status()).toBe(400);
  expect(await zh.json()).toMatchObject({ fields: [{ field: "filters.sources", code: "zh_nvwa_only" }] });
  const instant = await request.post("/api/manage", {
    data: { token, locale: "en", filters: { sources: ["rasff"] }, instant_sources: ["nvwa"] },
  });
  expect(instant.status()).toBe(400);
  const unknown = await request.post("/api/manage", {
    data: { token: "x".repeat(43), locale: "en", filters: { sources: ["rasff"] }, instant_sources: [] },
  });
  expect(unknown.status()).toBe(404);
  const form = await request.post("/api/manage", { form: { token } });
  expect(form.status()).toBe(415);
});

test("one-click unsubscribe (RFC 8058) works without cookies or JavaScript", async ({ request, baseURL }) => {
  const managePath = await activeSubscription(request, uniqueEmail("one-click"));
  const token = tokenOf(managePath);

  // Opening the link (mail scanners do) only redirects to the manage page.
  const opened = await request.get(`/api/unsubscribe?token=${token}`, { maxRedirects: 0 });
  expect(opened.status()).toBe(303);
  expect(opened.headers()["location"]).toBe(`${managePath}#unsubscribe`);
  expect((await subscriptionOf(request, managePath)).body.subscription?.status).toBe("active");

  // What a mail client sends for the List-Unsubscribe-Post header: a bare form POST.
  const mailClient = await apiRequest.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  const posted = await mailClient.post(`/api/unsubscribe?token=${token}`, {
    form: { "List-Unsubscribe": "One-Click" },
  });
  expect(posted.status()).toBe(200);
  expect(await posted.json()).toEqual({ status: "unsubscribed" });
  expect((await subscriptionOf(request, managePath)).body.subscription?.status).toBe("unsubscribed");
  // Repeating it is harmless.
  const again = await mailClient.post(`/api/unsubscribe?token=${token}`, { form: { "List-Unsubscribe": "One-Click" } });
  expect(again.status()).toBe(200);
  const wrongBody = await mailClient.post(`/api/unsubscribe?token=${token}`, { form: { other: "x" } });
  expect(wrongBody.status()).toBe(400);
  const unknown = await mailClient.post(`/api/unsubscribe?token=${"x".repeat(43)}`, {
    form: { "List-Unsubscribe": "One-Click" },
  });
  expect(unknown.status()).toBe(404);
  await mailClient.dispose();
});

test("the unsubscribe link from an email shows the unsubscribe button", async ({ page }) => {
  const managePath = await activeSubscription(page.request, uniqueEmail("link"));
  await page.goto(`/api/unsubscribe?token=${tokenOf(managePath)}`);
  await expect(page).toHaveURL(new RegExp(`${managePath}#unsubscribe$`));
  await page.getByRole("button", { name: "Unsubscribe" }).click();
  await expect(page.getByTestId("subscription-status")).toContainText("Unsubscribed on");
});

test("delete my data removes the Subscription and blocks the address", async ({ page }) => {
  const email = uniqueEmail("delete");
  const managePath = await activeSubscription(page.request, email);
  await page.goto(managePath);
  await page.getByRole("button", { name: "Delete my data" }).click();
  await expect(page.getByText("Are you sure? This cannot be undone.")).toBeVisible();
  await page.getByRole("button", { name: "Yes, delete my data" }).click();
  await expect(page.getByRole("status")).toContainText("Your data has been deleted");

  expect((await subscriptionOf(page.request, managePath)).status).toBe(404);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This link is not valid");

  // The address is on the do-not-send list: subscribing again looks the same but sends nothing.
  const again = await page.request.post("/api/subscribe", { data: subscribeBody(email) });
  expect(again.status()).toBe(202);
  await page.waitForTimeout(2_000);
  expect(messagesTo(email)).toHaveLength(1);
});

test("an invalid manage link explains itself, also in Chinese", async ({ page }) => {
  const response = await page.goto("/zh/alerts/manage/not-a-token");
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("此链接无效");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});
