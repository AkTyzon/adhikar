/**
 * Document analysis.
 *
 * Receives text the browser already extracted, never the file itself. That is a
 * privacy decision: a tenancy agreement or a legal notice never leaves the user's
 * machine as a document, only as the text needed to answer their question, and
 * nothing is written to disk at any point.
 */

import { NextResponse } from "next/server";

import { buildDocumentSystemPrompt, buildDocumentUserPrompt } from "@/lib/ai-prompt";
import { isLanguageCode } from "@/lib/languages";
import { ProviderError, resolveProvider, streamCompletion } from "@/lib/llm";
import { RateLimiter, clientKey } from "@/lib/rate-limit";

/** Roughly 30 pages of dense text. Beyond this the answer degrades anyway. */
const MAX_DOCUMENT_CHARS = 120_000;
const MIN_DOCUMENT_CHARS = 200;
/** Analysis costs more than a question, so it gets a tighter bucket. */
const limiter = new RateLimiter(6, 60_000);

const DEFAULT_QUESTION =
  "Summarise this document in plain language, list anything unfair or risky in it, and tell me what to do next.";

export async function POST(request: Request): Promise<Response> {
  const limit = limiter.check(clientKey(request));
  if (!limit.allowed) {
    return NextResponse.json(
      { error: "Too many documents analysed in a short time. Please wait a moment." },
      { status: 429, headers: { "retry-after": String(limit.retryAfter) } },
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "Expected a JSON body." }, { status: 400 });
  }

  const {
    documentText,
    question,
    language,
  } = payload as { documentText?: unknown; question?: unknown; language?: unknown };

  if (typeof documentText !== "string" || documentText.trim().length < MIN_DOCUMENT_CHARS) {
    return NextResponse.json(
      {
        error:
          "No readable text was found in that file. If it is a scan or a photo, Adhikar cannot read it yet — it has no OCR.",
      },
      { status: 400 },
    );
  }
  if (documentText.length > MAX_DOCUMENT_CHARS) {
    return NextResponse.json(
      { error: "That document is too long to analyse. Try the most relevant section of it." },
      { status: 413 },
    );
  }

  const languageCode = isLanguageCode(language) ? language : "en";
  const userQuestion =
    typeof question === "string" && question.trim().length > 4 ? question.trim().slice(0, 1_000) : DEFAULT_QUESTION;

  const provider = resolveProvider();
  if (!provider) {
    return NextResponse.json(
      {
        mode: "offline",
        error:
          "Document analysis needs an AI model. Set GOOGLE_GENERATIVE_AI_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY and restart. The scenario cards work without a key.",
      },
      { status: 503 },
    );
  }

  // A per-request random fence. A fixed delimiter can be written into the
  // document by its author to close the block early and promote the rest to
  // instructions; a random one cannot be guessed by whoever drafted the file.
  const fence = crypto.randomUUID();

  try {
    const stream = await streamCompletion(provider, {
      system: buildDocumentSystemPrompt(languageCode),
      user: buildDocumentUserPrompt(documentText.replaceAll(fence, "[removed]"), userQuestion, fence),
      maxTokens: 6_000,
    });

    return new Response(stream, {
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-adhikar-provider": provider.label,
      },
    });
  } catch (error) {
    if (error instanceof ProviderError) {
      console.error("[analyze-doc] provider failure", error.message);
      return NextResponse.json({ error: error.safeDetail }, { status: error.status });
    }
    console.error("[analyze-doc] unexpected failure", error);
    return NextResponse.json({ error: "Something went wrong. Please try again." }, { status: 500 });
  }
}
