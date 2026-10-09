import { describe, expect, it } from "vitest";
import { keyFromSegments, notificationPath } from "./notification-path";

describe("notificationPath", () => {
  it("puts an openFDA recall number in one segment", () => {
    expect(notificationPath("en", "openfda", "H-0015-2027")).toBe("/en/n/openfda/H-0015-2027");
  });

  it("keeps the dot of a RASFF reference", () => {
    expect(notificationPath("nl", "rasff", "2026.9489")).toBe("/nl/n/rasff/2026.9489");
  });

  it("spreads an NVWA URL path over segments, without the leading slash", () => {
    expect(
      notificationPath(
        "en",
        "nvwa",
        "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen",
      ),
    ).toBe(
      "/en/n/nvwa/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen",
    );
  });

  it("percent-encodes characters that are not safe in a segment", () => {
    expect(notificationPath("en", "openfda", "A B/C")).toBe("/en/n/openfda/A%20B%2FC");
  });
});

describe("keyFromSegments", () => {
  it("reads back an openFDA key", () => {
    expect(keyFromSegments("openfda", ["H-0015-2027"])).toBe("H-0015-2027");
  });

  it("rebuilds the NVWA URL path with its leading slash", () => {
    expect(keyFromSegments("nvwa", ["documenten", "2024", "01", "05", "slug"])).toBe(
      "/documenten/2024/01/05/slug",
    );
  });

  it("decodes percent-encoded segments", () => {
    expect(keyFromSegments("openfda", ["A%20B%2FC"])).toBe("A B/C");
  });

  it("rejects extra segments for Sources whose keys are a single segment", () => {
    expect(keyFromSegments("rasff", ["2026.9489", "extra"])).toBeNull();
  });

  it("rejects malformed percent-encoding", () => {
    expect(keyFromSegments("openfda", ["%E0%A4%A"])).toBeNull();
  });
});
