// Link formats shared with the Python mailer (pipeline/src/openfoodalerts/subscriptions/
// links.py); both test suites use the same literal values.
import { describe, expect, it } from "vitest";
import { manageToken } from "./crypto";
import { listUnsubscribeHeaders, manageUrl, tokenFromLink, unsubscribeUrl } from "./links";

const ID = "6f1c1f0e-3a8e-4c5a-9a53-2d1c3f6a7b8c";
// base64url(HMAC-SHA256("secret-1", "manage:v1:" + ID)), computed once with Node.js crypto.
// A public test vector, not a credential.
const TOKEN = "wJMitkeX3x6Sd7td2o5oR6N2GOoZW6yZk2swTVSV3C8"; // gitleaks:allow
const SITE = "https://openfoodalerts.nl";

describe("manage and unsubscribe links", () => {
  it("derives the same manage token as the Python mailer", () => {
    expect(manageToken(ID, "secret-1")).toBe(TOKEN);
  });

  it("formats the manage and one-click unsubscribe URLs", () => {
    expect(manageUrl(SITE, "nl", TOKEN)).toBe(`${SITE}/nl/alerts/manage/${TOKEN}`);
    expect(unsubscribeUrl(SITE, TOKEN)).toBe(`${SITE}/api/unsubscribe?token=${TOKEN}`);
    expect(unsubscribeUrl(`${SITE}/`, TOKEN)).toBe(`${SITE}/api/unsubscribe?token=${TOKEN}`);
  });

  it("builds the RFC 8058 headers", () => {
    expect(listUnsubscribeHeaders(SITE, TOKEN)).toEqual({
      "List-Unsubscribe": `<${SITE}/api/unsubscribe?token=${TOKEN}>`,
      "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    });
  });

  it("reads a token only when it has the token format", () => {
    expect(tokenFromLink(TOKEN)).toBe(TOKEN);
    expect(tokenFromLink(null)).toBeNull();
    expect(tokenFromLink(`${TOKEN}x`)).toBeNull();
    expect(tokenFromLink("../../etc/passwd")).toBeNull();
  });
});
