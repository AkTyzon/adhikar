/**
 * Bring-your-own-key handling.
 *
 * A visitor to a deployed instance can supply their own Gemini key so the demo
 * works even when the server holds no credentials. The header name matches the
 * convention used across these projects.
 *
 * Three rules, all enforced here so no route has to remember them:
 *
 * 1. The key is read from a header, never a query string -- query strings are
 *    recorded by access logs, proxies and browser history.
 * 2. It is shape-checked before use, so a typo fails fast instead of producing an
 *    opaque upstream 400.
 * 3. It is never logged, never stored, and never echoed in a response.
 */

import { type KeyOverride, looksLikeGeminiKey } from "./llm";

export const GEMINI_KEY_HEADER = "x-gemini-api-key";

/** Extract a caller-supplied key, if one was sent and looks plausible. */
export function readKeyOverride(request: Request): KeyOverride | undefined {
  const raw = request.headers.get(GEMINI_KEY_HEADER);
  if (!raw) return undefined;

  const key = raw.trim();
  // An unusable value is dropped rather than forwarded: sending it upstream would
  // waste a round trip and surface a provider error the user cannot act on.
  if (!looksLikeGeminiKey(key)) return undefined;
  return { gemini: key };
}
