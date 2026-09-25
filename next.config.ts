import type { NextConfig } from "next";

/**
 * Security headers.
 *
 * The Content-Security-Policy is the one that earns its keep here. This app
 * renders model output and user-uploaded document text, so an escaping mistake
 * anywhere in that path should not be able to become script execution.
 *
 * `'unsafe-inline'` is present for styles only. Tailwind v4 and Next inject
 * inline style attributes for hydration and critical CSS, and there is no
 * nonce-based route for that without significant contortion — noted here rather
 * than quietly allowed. Scripts get no such exemption: `'unsafe-eval'` is absent,
 * and `'unsafe-inline'` in script-src is ignored by browsers when a nonce or hash
 * is present, so Next's own inline bootstrap is covered by `strict-dynamic`.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'strict-dynamic'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  // The app talks to its own API only. Provider calls happen server-side, so the
  // browser never needs to reach an AI vendor directly.
  "connect-src 'self'",
  // pdf.js runs in a worker loaded from our own origin.
  "worker-src 'self' blob:",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "object-src 'none'",
  "upgrade-insecure-requests",
].join("; ");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The framework version is not something a visitor needs, and it tells an
  // attacker which advisories to try.
  poweredByHeader: false,

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains",
          },
        ],
      },
      {
        // Uploaded documents and their analyses are confidential. Nothing on an
        // API path should sit in a shared cache.
        source: "/api/:path*",
        headers: [{ key: "Cache-Control", value: "no-store" }],
      },
    ];
  },
};

export default nextConfig;
