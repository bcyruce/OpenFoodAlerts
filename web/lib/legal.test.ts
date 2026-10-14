import { describe, expect, it } from "vitest";
import { missingLegalFields, snelvinkUrl, type Operator } from "./legal";

describe("snelvinkUrl", () => {
  it("adds the UTM parameters of spec §11.3 rule 7", () => {
    expect(snelvinkUrl("about")).toBe(
      "https://snelvink.nl/?utm_source=openfoodalerts.nl&utm_medium=about&utm_campaign=v1",
    );
    expect(snelvinkUrl("footer")).toContain("utm_medium=footer");
  });
});

describe("missingLegalFields", () => {
  const complete: Operator = {
    tradeName: "OpenFoodAlerts",
    legalName: "Example",
    ownerName: "A. Person",
    address: ["Straat 1", "1234 AB Plaats"],
    email: "info@openfoodalerts.nl",
    kvk: "12345678",
    btwId: "NL000099998B57",
  };

  it("is empty when every BW 3:15d field is known", () => {
    expect(missingLegalFields(complete)).toEqual([]);
  });

  it("lists the fields that are still unknown", () => {
    expect(missingLegalFields({ ...complete, kvk: null, address: null })).toEqual(["address", "kvk"]);
  });
});
