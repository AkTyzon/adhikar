/**
 * Streaming LLM client for Gemini, OpenAI and Anthropic.
 *
 * Written against the providers' HTTP APIs directly rather than through the
 * Vercel AI SDK. That was a security decision before it was a design one: the SDK
 * version compatible with this project carried a filetype-bypass advisory and
 * pulled in `jsondiffpatch`, which has published XSS and prototype-pollution
 * findings. Removing it took `npm audit` to zero. What is left is one file we own,
 * three request builders, and one SSE parser.
 *
 * All three providers are wired because the brief names Gemini and OpenAI while
 * the operator of this deployment may hold an Anthropic key. Whichever key is
 * present is used; when none is, the caller falls back to the pre-written
 * scenario answers so the product still works.
 *
 * Every response is streamed as plain UTF-8 text chunks. The client renders
 * progressively and the route stays under any platform response timeout.
 */

export type ProviderId = "google" | "openai" | "anthropic";

export interface ProviderConfig {
  id: ProviderId;
  /** Human-readable name shown in the UI footer. */
  label: string;
  model: string;
  apiKey: string;
}

export interface CompletionRequest {
  system: string;
  user: string;
  /** Upper bound on generated tokens. Long legal answers need room. */
  maxTokens?: number;
  signal?: AbortSignal;
}

const DEFAULT_MAX_TOKENS = 4096;
/** Requests are abandoned after this long so a hung upstream cannot pin a worker. */
const REQUEST_TIMEOUT_MS = 60_000;

/**
 * Resolve the provider from the environment.
 *
 * Order is explicit rather than alphabetical: Gemini first because the brief
 * names it, then OpenAI, then Anthropic. Returns undefined when no key is set,
 * which is a supported state and not an error.
 */
export function resolveProvider(env: NodeJS.ProcessEnv = process.env): ProviderConfig | undefined {
  if (env.GOOGLE_GENERATIVE_AI_API_KEY) {
    return {
      id: "google",
      label: "Google Gemini",
      model: env.ADHIKAR_MODEL ?? "gemini-2.0-flash",
      apiKey: env.GOOGLE_GENERATIVE_AI_API_KEY,
    };
  }
  if (env.OPENAI_API_KEY) {
    return {
      id: "openai",
      label: "OpenAI",
      model: env.ADHIKAR_MODEL ?? "gpt-4o-mini",
      apiKey: env.OPENAI_API_KEY,
    };
  }
  if (env.ANTHROPIC_API_KEY) {
    return {
      id: "anthropic",
      label: "Anthropic Claude",
      model: env.ADHIKAR_MODEL ?? "claude-opus-5",
      apiKey: env.ANTHROPIC_API_KEY,
    };
  }
  return undefined;
}

export class ProviderError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Safe to show a user. The full message goes only to the server log. */
    readonly safeDetail: string,
  ) {
    super(message);
    this.name = "ProviderError";
  }
}

interface Endpoint {
  url: string;
  headers: Record<string, string>;
  body: unknown;
  /** Pull the text delta out of one parsed SSE payload. */
  extractDelta: (payload: unknown) => string;
}

function buildEndpoint(provider: ProviderConfig, request: CompletionRequest): Endpoint {
  const maxTokens = request.maxTokens ?? DEFAULT_MAX_TOKENS;

  switch (provider.id) {
    case "google":
      return {
        // Key travels as a header, not a query parameter: query strings end up in
        // access logs and proxy logs.
        url: `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
          provider.model,
        )}:streamGenerateContent?alt=sse`,
        headers: {
          "content-type": "application/json",
          "x-goog-api-key": provider.apiKey,
        },
        body: {
          systemInstruction: { parts: [{ text: request.system }] },
          contents: [{ role: "user", parts: [{ text: request.user }] }],
          generationConfig: { maxOutputTokens: maxTokens, temperature: 0.3 },
        },
        extractDelta: (payload) => {
          const parts = (payload as GoogleChunk)?.candidates?.[0]?.content?.parts;
          return parts?.map((part) => part.text ?? "").join("") ?? "";
        },
      };

    case "openai":
      return {
        url: "https://api.openai.com/v1/chat/completions",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${provider.apiKey}`,
        },
        body: {
          model: provider.model,
          stream: true,
          max_completion_tokens: maxTokens,
          temperature: 0.3,
          messages: [
            { role: "system", content: request.system },
            { role: "user", content: request.user },
          ],
        },
        extractDelta: (payload) => (payload as OpenAiChunk)?.choices?.[0]?.delta?.content ?? "",
      };

    case "anthropic":
      return {
        url: "https://api.anthropic.com/v1/messages",
        headers: {
          "content-type": "application/json",
          "x-api-key": provider.apiKey,
          "anthropic-version": "2023-06-01",
        },
        body: {
          model: provider.model,
          stream: true,
          max_tokens: maxTokens,
          temperature: 0.3,
          system: request.system,
          messages: [{ role: "user", content: request.user }],
        },
        extractDelta: (payload) => {
          const chunk = payload as AnthropicChunk;
          return chunk?.type === "content_block_delta" ? (chunk.delta?.text ?? "") : "";
        },
      };
  }
}

interface GoogleChunk {
  candidates?: { content?: { parts?: { text?: string }[] } }[];
}
interface OpenAiChunk {
  choices?: { delta?: { content?: string } }[];
}
interface AnthropicChunk {
  type?: string;
  delta?: { text?: string };
}

/**
 * Stream a completion as plain text chunks.
 *
 * Throws `ProviderError` before returning if the upstream rejects the request, so
 * a caller can respond with a status code rather than a half-open stream that
 * fails silently in the browser.
 */
export async function streamCompletion(
  provider: ProviderConfig,
  request: CompletionRequest,
): Promise<ReadableStream<Uint8Array>> {
  const endpoint = buildEndpoint(provider, request);

  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const signal = request.signal ? AbortSignal.any([request.signal, timeout]) : timeout;

  let upstream: Response;
  try {
    upstream = await fetch(endpoint.url, {
      method: "POST",
      headers: endpoint.headers,
      body: JSON.stringify(endpoint.body),
      signal,
    });
  } catch (cause) {
    const aborted = cause instanceof Error && cause.name === "TimeoutError";
    throw new ProviderError(
      `${provider.id} request failed: ${String(cause)}`,
      aborted ? 504 : 502,
      aborted ? "The model took too long to respond. Please try again." : "Could not reach the AI service.",
    );
  }

  if (!upstream.ok || !upstream.body) {
    // Read the body for the log, but never forward it: provider errors can echo
    // request content and occasionally key metadata.
    const detail = await upstream.text().catch(() => "");
    throw new ProviderError(
      `${provider.id} returned ${upstream.status}: ${detail.slice(0, 500)}`,
      upstream.status === 429 ? 429 : 502,
      upstream.status === 429
        ? "The AI service is rate limited right now. Please try again in a moment."
        : "The AI service rejected this request.",
    );
  }

  return toTextStream(upstream.body, endpoint.extractDelta);
}

/**
 * Convert a provider's SSE body into a stream of plain text.
 *
 * Buffers by line because an SSE event can be split across network chunks —
 * parsing each chunk independently drops tokens at the seams, which shows up as
 * words missing from the middle of an answer.
 */
function toTextStream(
  body: ReadableStream<Uint8Array>,
  extractDelta: (payload: unknown) => string,
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const reader = body.getReader();
  let buffer = "";

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read();

      if (done) {
        flushLine(buffer, controller);
        controller.close();
        return;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // The final element may be a partial line; keep it for the next pull.
      buffer = lines.pop() ?? "";

      for (const line of lines) flushLine(line, controller);
    },

    cancel(reason) {
      // Propagate cancellation so a closed browser tab stops the upstream call
      // instead of leaving it billing until it completes.
      void reader.cancel(reason);
    },
  });

  function flushLine(line: string, controller: ReadableStreamDefaultController<Uint8Array>) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) return;

    const data = trimmed.slice(5).trim();
    if (!data || data === "[DONE]") return;

    try {
      const text = extractDelta(JSON.parse(data));
      if (text) controller.enqueue(encoder.encode(text));
    } catch {
      // A malformed chunk is skipped rather than failing the whole answer. The
      // alternative is losing a complete response to one bad frame.
    }
  }
}
