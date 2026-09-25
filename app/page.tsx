/**
 * Server entry point.
 *
 * A server component so two things can be resolved before any JavaScript runs:
 *
 * 1. **Which model is configured.** The reader is entitled to know whether an
 *    answer came from a live model or from Adhikar's pre-written text, and asking
 *    the client to discover that would mean an extra round trip and a moment where
 *    the UI cannot say.
 *
 * 2. **A question submitted before hydration.** The search form is a real form
 *    with a GET action, so pressing Enter works whether or not React has attached
 *    its handlers yet. The question arrives here as a search parameter and is run
 *    on mount. Without this, an early submit reloaded the page and lost the
 *    question — which is precisely what it did.
 */

import { AdhikarApp } from "@/components/AdhikarApp";
import { resolveProvider } from "@/lib/llm";

export default async function Page({
  searchParams,
}: {
  // Next 15+ passes search params as a promise.
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const raw = params.question;
  const question = (Array.isArray(raw) ? raw[0] : raw) ?? "";

  // Resolved server-side; only the label crosses to the client, never the key.
  const provider = resolveProvider();

  return (
    <AdhikarApp
      providerLabel={provider ? `${provider.label} · ${provider.model}` : null}
      initialQuestion={question.slice(0, 1_000)}
    />
  );
}
