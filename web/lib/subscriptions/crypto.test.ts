import { createHash, createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { emailHash, ipHash, manageToken, newConfirmToken, tokenHash } from "./crypto";

describe("token helpers", () => {
  it("creates unguessable URL-safe confirm tokens", () => {
    const a = newConfirmToken();
    const b = newConfirmToken();
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(a).not.toBe(b);
  });

  it("stores tokens as SHA-256 hex", () => {
    // Known SHA-256 of "abc" (FIPS 180-2 example).
    expect(tokenHash("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("derives the manage token from the Subscription id with the token secret", () => {
    const id = "6f1c1f0e-3a8e-4c5a-9a53-2d1c3f6a7b8c";
    const token = manageToken(id, "secret-1");
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(manageToken(id, "secret-1")).toBe(token);
    expect(manageToken(id, "secret-2")).not.toBe(token);
    expect(manageToken("00000000-0000-4000-8000-000000000000", "secret-1")).not.toBe(token);
    // Cross-language contract (the Python mailer rebuilds manage links the same way).
    expect(token).toBe(
      createHmac("sha256", "secret-1").update(`manage:v1:${id}`).digest("base64url"),
    );
  });

  it("hashes normalized emails with the pepper, so the same address always matches", () => {
    const h = emailHash(" Jan@Example.NL", "pepper");
    expect(h).toMatch(/^[0-9a-f]{64}$/);
    expect(emailHash("jan@example.nl", "pepper")).toBe(h);
    expect(emailHash("jan@example.nl", "other")).not.toBe(h);
    // Not a plain hash: a leaked suppression list cannot be checked against an address list.
    expect(h).not.toBe(createHash("sha256").update("jan@example.nl").digest("hex"));
    expect(h).toBe(createHmac("sha256", "pepper").update("email:v1:jan@example.nl").digest("hex"));
  });

  it("hashes IP addresses with the pepper and a separate domain", () => {
    const h = ipHash("203.0.113.7", "pepper");
    expect(h).toMatch(/^[0-9a-f]{64}$/);
    expect(h).not.toBe(ipHash("203.0.113.8", "pepper"));
    expect(h).not.toBe(emailHash("203.0.113.7", "pepper"));
  });
});
