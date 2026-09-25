/**
 * In-process rate limiter.
 *
 * A token bucket per client. Deliberately simple and deliberately in-memory: the
 * point is to stop one visitor exhausting the deployment's model budget, not to
 * be a distributed quota system. A serverless deployment gets one bucket per warm
 * instance, which weakens it — noted here rather than hidden, and the fix is a
 * shared store (Upstash, Redis) behind the same `check()` signature.
 */

interface Bucket {
  tokens: number;
  updatedAt: number;
}

export interface LimitResult {
  allowed: boolean;
  /** Seconds until the next token, for a Retry-After header. */
  retryAfter: number;
}

export class RateLimiter {
  private readonly buckets = new Map<string, Bucket>();
  private readonly refillPerMs: number;

  constructor(
    private readonly capacity: number,
    windowMs: number,
  ) {
    this.refillPerMs = capacity / windowMs;
  }

  check(key: string, cost = 1): LimitResult {
    const now = Date.now();
    const bucket = this.buckets.get(key) ?? { tokens: this.capacity, updatedAt: now };

    bucket.tokens = Math.min(this.capacity, bucket.tokens + (now - bucket.updatedAt) * this.refillPerMs);
    bucket.updatedAt = now;

    if (bucket.tokens >= cost) {
      bucket.tokens -= cost;
      this.buckets.set(key, bucket);
      return { allowed: true, retryAfter: 0 };
    }

    this.buckets.set(key, bucket);
    const deficit = cost - bucket.tokens;
    return { allowed: false, retryAfter: Math.max(1, Math.ceil(deficit / this.refillPerMs / 1000)) };
  }

  /** Drop buckets that have fully refilled, so the map cannot grow without bound. */
  sweep(): void {
    const now = Date.now();
    for (const [key, bucket] of this.buckets) {
      const refilled = bucket.tokens + (now - bucket.updatedAt) * this.refillPerMs;
      if (refilled >= this.capacity) this.buckets.delete(key);
    }
  }
}

/**
 * Identify the caller.
 *
 * Behind Vercel or a similar proxy, `x-forwarded-for` is set by the platform and
 * is the only address available. It is client-spoofable in a self-hosted setup
 * without a trusted proxy, so this is a budget guard rather than a security
 * boundary, and it is labelled as such.
 */
export function clientKey(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0]!.trim();
  return request.headers.get("x-real-ip") ?? "unknown";
}
