import { describe, expect, it } from "vitest";
import { renderEmail } from "./render";
import { renderConfirmEmail } from "./templates";

const CONFIRM_URL = "https://openfoodalerts.nl/nl/alerts/confirm#token=abc_DEF-123";

const choices = {
  filters: {
    sources: ["nvwa" as const, "rasff" as const],
    hazard_categories: [21798],
    product_categories: [],
    origin_countries: [],
  },
  includeUnclassified: true,
  instantSources: ["nvwa" as const],
};

describe("renderEmail", () => {
  it("renders the same blocks as plain text and as escaped HTML", () => {
    const email = renderEmail({
      locale: "en",
      subject: "Subject <1>",
      blocks: [
        { kind: "paragraph", text: "Hello <script>alert(1)</script> & welcome" },
        { kind: "list", items: ["one", "two"] },
        { kind: "button", label: "Go", url: "https://example.org/?a=1&b=2" },
        { kind: "note", text: "Small print" },
      ],
      footer: ["Footer line"],
    });
    expect(email.subject).toBe("Subject <1>");
    expect(email.text).toBe(
      [
        "Hello <script>alert(1)</script> & welcome",
        "- one\n- two",
        "Go:\nhttps://example.org/?a=1&b=2",
        "Small print",
        "--\nFooter line",
      ].join("\n\n") + "\n",
    );
    expect(email.html).toContain('<html lang="en">');
    expect(email.html).toContain("Hello &lt;script&gt;alert(1)&lt;/script&gt; &amp; welcome");
    expect(email.html).toContain('href="https://example.org/?a=1&amp;b=2"');
    expect(email.html).not.toContain("<script>");
  });

  it("marks Chinese emails as Simplified Chinese", () => {
    const email = renderEmail({ locale: "zh", subject: "主题", blocks: [], footer: [] });
    expect(email.html).toContain('<html lang="zh-Hans">');
  });
});

describe("renderConfirmEmail", () => {
  it("renders the English confirmation email with the link and the chosen filters", () => {
    const email = renderConfirmEmail({ locale: "en", confirmUrl: CONFIRM_URL, ...choices });
    expect(email.subject).toBe("Confirm your OpenFoodAlerts subscription");
    expect(email.text).toContain(CONFIRM_URL);
    expect(email.text).toContain("Sources: NVWA, RASFF");
    expect(email.text).toContain("Hazard categories: 1 selected");
    expect(email.text).toContain("Product categories: all");
    expect(email.text).toContain("Instant email: NVWA");
    expect(email.text).toContain("24 hours");
    expect(email.html).toContain(`href="${CONFIRM_URL}"`);
  });

  it("is localized in Dutch and Chinese", () => {
    const nl = renderConfirmEmail({ locale: "nl", confirmUrl: CONFIRM_URL, ...choices });
    expect(nl.subject).toBe("Bevestig uw abonnement op OpenFoodAlerts");
    expect(nl.text).toContain("24 uur");
    const zh = renderConfirmEmail({
      locale: "zh",
      confirmUrl: CONFIRM_URL,
      ...choices,
      filters: { ...choices.filters, sources: ["nvwa"] },
    });
    expect(zh.subject).toBe("请确认您的 OpenFoodAlerts 订阅");
    expect(zh.text).toContain("24 小时");
    expect(zh.html).toContain('lang="zh-Hans"');
  });

  it("says when every Source is included and no Instant emails were chosen", () => {
    const email = renderConfirmEmail({
      locale: "en",
      confirmUrl: CONFIRM_URL,
      ...choices,
      filters: { ...choices.filters, sources: [] },
      instantSources: [],
    });
    expect(email.text).toContain("Sources: all");
    expect(email.text).toContain("Instant email: none");
  });

  it("contains no promotional content", () => {
    for (const locale of ["en", "nl", "zh"] as const) {
      const email = renderConfirmEmail({ locale, confirmUrl: CONFIRM_URL, ...choices });
      expect(`${email.text}${email.html}`).not.toMatch(/snelvink|utm_|advert/i);
    }
  });
});
