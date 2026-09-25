/**
 * Rate limiting.
 *
 * This guards the deployment's model budget. One visitor holding the endpoint
 * open is the difference between a working demo and an exhausted quota.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { RateLimiter, clientKey } from "../lib/rate-limit";

describe("token bucket", () => {
  it("allows up to capacity then refuses", () => {
    const limiter = new RateLimiter(3, 60_000);
    assert.deepEqual(
      [1, 2, 3, 4].map(() => limiter.check("client").allowed),
      [true, true, true, false],
    );
  });

  it("tells a refused caller when to retry", () => {
    const limiter = new RateLimiter(1, 60_000);
    limiter.check("client");
    const result = limiter.check("client");
    assert.equal(result.allowed, false);
    assert.ok(result.retryAfter > 0);
  });

  it("keeps clients separate", () => {
    const limiter = new RateLimiter(1, 60_000);
    assert.equal(limiter.check("a").allowed, true);
    assert.equal(limiter.check("b").allowed, true);
    assert.equal(limiter.check("a").allowed, false);
  });

  it("refills over time", async () => {
    const limiter = new RateLimiter(2, 100);
    limiter.check("client");
    limiter.check("client");
    assert.equal(limiter.check("client").allowed, false);
    await new Promise((resolve) => setTimeout(resolve, 120));
    assert.equal(limiter.check("client").allowed, true);
  });

  it("sweeps fully-refilled buckets so the map cannot grow without bound", async () => {
    const limiter = new RateLimiter(1, 50);
    for (let i = 0; i < 100; i += 1) limiter.check(`client-${i}`);
    await new Promise((resolve) => setTimeout(resolve, 80));
    limiter.sweep();
    // Every bucket has refilled, so a fresh request is allowed again.
    assert.equal(limiter.check("client-0").allowed, true);
  });
});

describe("identifying a client", () => {
  it("takes the first address from x-forwarded-for", () => {
    const request = new Request("https://example.test", {
      headers: { "x-forwarded-for": "203.0.113.7, 198.51.100.1" },
    });
    assert.equal(clientKey(request), "203.0.113.7");
  });

  it("falls back to x-real-ip", () => {
    const request = new Request("https://example.test", { headers: { "x-real-ip": "203.0.113.9" } });
    assert.equal(clientKey(request), "203.0.113.9");
  });

  it("returns a stable key when no address is available", () => {
    assert.equal(clientKey(new Request("https://example.test")), "unknown");
  });
});
