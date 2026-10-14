import { describe, expect, it } from "vitest";
import { ownerName, snelvinkUrl } from "./referral";

describe("snelvinkUrl", () => {
  // Spec §11.3 rule 7.
  it("adds the UTM parameters for each placement", () => {
    expect(snelvinkUrl("footer", "https://snelvink.nl")).toBe(
      "https://snelvink.nl/?utm_source=openfoodalerts.nl&utm_medium=footer&utm_campaign=v1",
    );
    expect(snelvinkUrl("home_box", "https://snelvink.nl/")).toBe(
      "https://snelvink.nl/?utm_source=openfoodalerts.nl&utm_medium=home_box&utm_campaign=v1",
    );
    expect(snelvinkUrl("zh_box", "https://snelvink.nl")).toContain("utm_medium=zh_box");
    expect(snelvinkUrl("about", "https://snelvink.nl")).toContain("utm_medium=about");
  });

  it("keeps a path and existing parameters of the configured URL", () => {
    expect(snelvinkUrl("footer", "https://example.nl/nl?lang=nl")).toBe(
      "https://example.nl/nl?lang=nl&utm_source=openfoodalerts.nl&utm_medium=footer&utm_campaign=v1",
    );
  });
});

describe("ownerName", () => {
  it("uses the configured name, else the placeholder", () => {
    expect(ownerName("Jane Doe", "the maintainer")).toBe("Jane Doe");
    expect(ownerName("  ", "the maintainer")).toBe("the maintainer");
    expect(ownerName(undefined, "de beheerder")).toBe("de beheerder");
  });
});
