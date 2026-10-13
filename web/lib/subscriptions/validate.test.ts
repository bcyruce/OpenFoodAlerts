import { describe, expect, it } from "vitest";
import { CONSENT_TEXT_VERSION } from "./consent";
import { parseSubscriptionRequest, parseSubscriptionSettings, type KnownFilterValues } from "./validate";

const known: KnownFilterValues = {
  hazardCategories: [21782, 21798],
  productCategories: [30001, 30002],
  countries: ["NL", "CN", "US"],
};

function body(overrides: Record<string, unknown> = {}) {
  return {
    email: "  Jan.Jansen@Example.NL ",
    locale: "nl",
    filters: {
      sources: ["rasff", "nvwa"],
      hazard_categories: [21798],
      product_categories: [],
      origin_countries: [],
    },
    include_unclassified: true,
    instant_sources: ["nvwa"],
    consent: true,
    consent_text_version: CONSENT_TEXT_VERSION,
    ...overrides,
  };
}

function errorFields(raw: unknown): string[] {
  const result = parseSubscriptionRequest(raw, known);
  if (result.ok) throw new Error("expected errors");
  return result.errors.map((e) => e.field);
}

describe("parseSubscriptionRequest", () => {
  it("accepts a valid request and normalizes the email", () => {
    const result = parseSubscriptionRequest(body(), known);
    expect(result).toEqual({
      ok: true,
      value: {
        email: "jan.jansen@example.nl",
        locale: "nl",
        filters: {
          sources: ["nvwa", "rasff"],
          hazard_categories: [21798],
          product_categories: [],
          origin_countries: [],
        },
        includeUnclassified: true,
        instantSources: ["nvwa"],
        consentTextVersion: CONSENT_TEXT_VERSION,
      },
    });
  });

  it("treats missing filter arrays as no restriction and include_unclassified as true", () => {
    const result = parseSubscriptionRequest(
      body({ filters: {}, include_unclassified: undefined, instant_sources: undefined }),
      known,
    );
    expect(result.ok && result.value).toMatchObject({
      filters: { sources: [], hazard_categories: [], product_categories: [], origin_countries: [] },
      includeUnclassified: true,
      instantSources: [],
    });
  });

  it("rejects malformed and overlong email addresses", () => {
    expect(errorFields(body({ email: "not-an-email" }))).toEqual(["email"]);
    expect(errorFields(body({ email: "a b@example.nl" }))).toEqual(["email"]);
    expect(errorFields(body({ email: `${"x".repeat(250)}@example.nl` }))).toEqual(["email"]);
    expect(errorFields(body({ email: 42 }))).toEqual(["email"]);
  });

  it("rejects unknown locales, Sources, categories and countries", () => {
    expect(errorFields(body({ locale: "fr" }))).toEqual(["locale"]);
    expect(
      errorFields(
        body({
          filters: {
            sources: ["efsa"],
            hazard_categories: [1],
            product_categories: ["30001"],
            origin_countries: ["XX"],
          },
          instant_sources: [],
        }),
      ),
    ).toEqual([
      "filters.sources",
      "filters.hazard_categories",
      "filters.product_categories",
      "filters.origin_countries",
    ]);
  });

  it("allows only NVWA for Chinese Subscriptions", () => {
    expect(errorFields(body({ locale: "zh" }))).toEqual(["filters.sources"]);
    expect(errorFields(body({ locale: "zh", filters: { sources: [] }, instant_sources: [] }))).toEqual(
      ["filters.sources"],
    );
    const ok = parseSubscriptionRequest(
      body({ locale: "zh", filters: { sources: ["nvwa"] }, instant_sources: ["nvwa"] }),
      known,
    );
    expect(ok.ok).toBe(true);
  });

  it("requires instant_sources to be a subset of the chosen Sources", () => {
    expect(errorFields(body({ instant_sources: ["openfda"] }))).toEqual(["instant_sources"]);
    // No Source restriction: any Source may have Instant emails.
    const ok = parseSubscriptionRequest(
      body({ filters: { sources: [] }, instant_sources: ["openfda", "rasff"] }),
      known,
    );
    expect(ok.ok && ok.value.instantSources).toEqual(["openfda", "rasff"]);
  });

  it("requires consent to the current consent text", () => {
    expect(errorFields(body({ consent: false }))).toEqual(["consent"]);
    expect(errorFields(body({ consent_text_version: "2000-01-01" }))).toEqual([
      "consent_text_version",
    ]);
  });

  it("rejects a body that is not an object", () => {
    expect(errorFields(null)).toEqual(["body"]);
    expect(errorFields([1])).toEqual(["body"]);
  });
});

describe("parseSubscriptionSettings (manage page, ticket 29)", () => {
  function settings(overrides: Record<string, unknown> = {}) {
    const all: Record<string, unknown> = body(overrides);
    delete all.email;
    delete all.consent;
    delete all.consent_text_version;
    return all;
  }

  it("accepts the editable fields, without email or consent", () => {
    expect(parseSubscriptionSettings(settings({ token: "ignored" }), known)).toEqual({
      ok: true,
      value: {
        locale: "nl",
        filters: {
          sources: ["nvwa", "rasff"],
          hazard_categories: [21798],
          product_categories: [],
          origin_countries: [],
        },
        includeUnclassified: true,
        instantSources: ["nvwa"],
      },
    });
  });

  it("applies the same rules as subscribing: zh means NVWA only, instant within sources", () => {
    expect(parseSubscriptionSettings(settings({ locale: "zh" }), known)).toEqual({
      ok: false,
      errors: [{ field: "filters.sources", code: "zh_nvwa_only" }],
    });
    expect(
      parseSubscriptionSettings(settings({ filters: { sources: ["rasff"] }, instant_sources: ["nvwa"] }), known),
    ).toEqual({ ok: false, errors: [{ field: "instant_sources", code: "not_in_sources" }] });
    expect(parseSubscriptionSettings(settings({ filters: { hazard_categories: [1] } }), known)).toEqual({
      ok: false,
      errors: [{ field: "filters.hazard_categories", code: "invalid" }],
    });
  });
});
