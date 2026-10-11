import { describe, expect, it } from "vitest";
import { clientIp, createRateLimiter, parseRateLimit } from "./rate-limit";

describe("createRateLimiter", () => {
  it("allows `limit` hits per key within the window, then reports when to retry", () => {
    let now = 1_000_000;
    const limiter = createRateLimiter({ limit: 2, windowMs: 60_000, now: () => now });
    expect(limiter.hit("a")).toEqual({ allowed: true, retryAfterSeconds: 0 });
    now += 10_000;
    expect(limiter.hit("a").allowed).toBe(true);
    now += 10_000;
    expect(limiter.hit("a")).toEqual({ allowed: false, retryAfterSeconds: 40 });
    expect(limiter.hit("b").allowed).toBe(true);
    now += 40_000;
    expect(limiter.hit("a").allowed).toBe(true);
  });

  it("forgets old keys so memory stays bounded", () => {
    let now = 0;
    const limiter = createRateLimiter({ limit: 1, windowMs: 1_000, now: () => now, maxKeys: 3 });
    for (const key of ["a", "b", "c", "d"]) limiter.hit(key);
    expect(limiter.size()).toBeLessThanOrEqual(3);
    now += 2_000;
    limiter.hit("e");
    expect(limiter.size()).toBe(1);
  });
});

describe("parseRateLimit", () => {
  it("reads COUNT/SECONDS and falls back on bad input", () => {
    expect(parseRateLimit("5/600", { limit: 1, windowMs: 1 })).toEqual({ limit: 5, windowMs: 600_000 });
    expect(parseRateLimit(undefined, { limit: 1, windowMs: 1 })).toEqual({ limit: 1, windowMs: 1 });
    expect(parseRateLimit("lots", { limit: 1, windowMs: 1 })).toEqual({ limit: 1, windowMs: 1 });
  });
});

describe("clientIp", () => {
  it("takes the address appended by the nearest proxy (last entry)", () => {
    const headers = new Headers({ "x-forwarded-for": "198.51.100.1, 203.0.113.7" });
    expect(clientIp(headers, "x-forwarded-for")).toBe("203.0.113.7");
    expect(clientIp(new Headers({ "x-real-ip": "2001:db8::1" }), "x-real-ip")).toBe("2001:db8::1");
  });

  it("returns null for a missing or malformed header", () => {
    expect(clientIp(new Headers(), "x-forwarded-for")).toBeNull();
    expect(clientIp(new Headers({ "x-forwarded-for": "evil" }), "x-forwarded-for")).toBeNull();
  });
});
