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

export type ProviderId = "google" | "openai" | "anthropic" | "local";

export interface ProviderConfig {
  id: ProviderId;
  /** Human-readable name shown in the UI footer. */
  label: string;
  model: string;
  apiKey: string;
  /** OpenAI-compatible base URL. Only used by the `local` provider. */
  baseUrl?: string;
  /** How long to wait for the first byte. */
  setupTimeoutMs?: number;
  /** How long to tolerate silence between chunks once streaming has begun. */
  idleTimeoutMs?: number;
  /** True when inference happens on this machine and no data leaves it. */
  onDevice?: boolean;
  /**
   * Suppress a reasoning model's thinking phase.
   *
   * Measured on qwen3:8b through Ollama: with thinking on, a 250-token budget was
   * spent entirely in the `reasoning` field and produced **zero** content tokens,
   * so the answer never arrived. `reasoning_effort: "none"` yielded a complete
   * answer in nine seconds. (Qwen's own `/no_think` prompt convention had no
   * effect through this endpoint.)
   */
  suppressReasoning?: boolean;
}

export interface CompletionRequest {
  system: string;
  user: string;
  /** Upper bound on generated tokens. Long legal answers need room. */
  maxTokens?: number;
  /**
   * Caller-supplied cancellation.
   *
   * Do **not** pass a route's incoming `request.signal` here. Once the request
   * body has been read and the handler is returning a streaming Response, that
   * signal is already spent, and forwarding it aborts the upstream call the
   * instant it starts -- which presented as a route that returned 200 with an
   * empty body while the model itself was demonstrably fine. Client disconnects
   * are propagated by the returned stream's `cancel()` callback instead, which is
   * the mechanism designed for it.
   */
  signal?: AbortSignal;
}

const DEFAULT_MAX_TOKENS = 4096;

/**
 * Timeouts come in two parts, because one wall-clock deadline is wrong for this.
 *
 * `setupMs` bounds how long we wait for the first byte -- an unreachable or
 * overloaded server must not hold a worker. `idleMs` then bounds the gap
 * *between* chunks once tokens are flowing.
 *
 * A single overall deadline was the original design and it was a bug: a local 8B
 * model producing a long structured answer streams healthily for minutes, and a
 * 60-second ceiling aborted it mid-sentence. An idle watchdog kills a genuinely
 * hung stream while letting a slow but live one finish.
 */
const SETUP_TIMEOUT_MS = 30_000;
const IDLE_TIMEOUT_MS = 45_000;
/**
 * A local model's first token can lag badly while weights load from disk, and a
 * reasoning model then goes quiet for a long stretch while it thinks -- Ollama
 * reports that phase in a separate `reasoning` field, so `content` genuinely
 * produces nothing for a while. Both windows are therefore much wider on device.
 */
const LOCAL_SETUP_TIMEOUT_MS = 120_000;
const LOCAL_IDLE_TIMEOUT_MS = 180_000;

/** Default endpoint for Ollama's OpenAI-compatible API. */
const DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1";

/**
 * Resolve the provider from the environment.
 *
 * Order is explicit rather than alphabetical: Gemini first because the brief
 * names it, then OpenAI, then Anthropic. Returns undefined when no key is set,
 * which is a supported state and not an error.
 */
export function resolveProvider(env: NodeJS.ProcessEnv = process.env): ProviderConfig | undefined {
  // Local first. Configuring an on-device model is a deliberate privacy choice,
  // and it should not be silently overridden by a cloud key left in the
  // environment from something else.
  if (env.ADHIKAR_LOCAL_MODEL || env.ADHIKAR_LOCAL_BASE_URL) {
    const model = env.ADHIKAR_LOCAL_MODEL ?? "qwen3:8b";
    return {
      id: "local",
      label: `On-device (${env.ADHIKAR_LOCAL_LABEL ?? "Ollama"})`,
      model,
      // OpenAI-compatible servers require the header to be present but do not
      // check it. Ollama ignores the value entirely.
      apiKey: env.ADHIKAR_LOCAL_API_KEY ?? "not-needed",
      baseUrl: (env.ADHIKAR_LOCAL_BASE_URL ?? DEFAULT_LOCAL_BASE_URL).replace(/\/+$/, ""),
      setupTimeoutMs: LOCAL_SETUP_TIMEOUT_MS,
      idleTimeoutMs: LOCAL_IDLE_TIMEOUT_MS,
      // Set ADHIKAR_LOCAL_THINKING=1 to let a reasoning model think. Off by
      // default because with it on, an 8B model can exhaust its whole budget
      // reasoning and emit no answer at all.
      suppressReasoning: env.ADHIKAR_LOCAL_THINKING !== "1",
      onDevice: true,
    };
  }

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

export interface Endpoint {
  url: string;
  headers: Record<string, string>;
  body: unknown;
  /** Pull the text delta out of one parsed SSE payload. */
  extractDelta: (payload: unknown) => string;
}

/** Exported so tests can assert the exact request body sent to each provider. */
export function buildEndpoint(provider: ProviderConfig, request: CompletionRequest): Endpoint {
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

    case "local":
      return {
        // Ollama, LM Studio, llama.cpp and vLLM all expose this shape, so one
        // implementation covers every local runtime worth supporting.
        url: `${provider.baseUrl ?? DEFAULT_LOCAL_BASE_URL}/chat/completions`,
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${provider.apiKey}`,
        },
        body: {
          model: provider.model,
          stream: true,
          max_tokens: maxTokens,
          temperature: 0.3,
          // Ignored by runtimes that do not implement it, which is why it is safe
          // to send unconditionally to any OpenAI-compatible local server.
          ...(provider.suppressReasoning ? { reasoning_effort: "none" } : {}),
          messages: [
            { role: "system", content: request.system },
            { role: "user", content: request.user },
          ],
        },
        // Ollama places a reasoning model's chain of thought in a separate
        // `reasoning` field, so reading `content` alone already excludes it.
        // Some runtimes instead inline <think> blocks in content; those are
        // stripped downstream by stripReasoning().
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

  // Aborts setup only. Cleared as soon as headers arrive, so it can never fire
  // against a stream that is actively delivering tokens.
  const setup = new AbortController();
  const setupTimer = setTimeout(
    () => setup.abort(new DOMException("setup timed out", "TimeoutError")),
    provider.setupTimeoutMs ?? SETUP_TIMEOUT_MS,
  );
  const signal = request.signal
    ? AbortSignal.any([request.signal, setup.signal])
    : setup.signal;

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
      aborted
        ? "The model took too long to respond. Please try again."
        : provider.onDevice
          ? `Could not reach the local model server at ${provider.baseUrl}. Is it running? Try: ollama serve`
          : "Could not reach the AI service.",
    );
  } finally {
    clearTimeout(setupTimer);
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

  return toTextStream(upstream.body, endpoint.extractDelta, {
    idleMs: provider.idleTimeoutMs ?? IDLE_TIMEOUT_MS,
    label: provider.id,
  });
}

/**
 * Strip inlined reasoning blocks from a token stream.
 *
 * Ollama's OpenAI-compatible endpoint puts a reasoning model's chain of thought
 * in a separate `reasoning` field, so reading `content` already excludes it. Other
 * local runtimes -- llama.cpp and some LM Studio builds -- inline it as
 * <think>...</think> inside the content instead, and a citizen reading a legal
 * answer should not be shown the model talking to itself.
 *
 * Stateful by necessity: an opening or closing tag can be split across network
 * chunks, so a per-chunk regex would let fragments through. Returns a function
 * that filters each chunk in order.
 */
export function createReasoningStripper(): (chunk: string) => string {
  const OPEN = "<think>";
  const CLOSE = "</think>";
  let inside = false;
  // Holds a trailing partial tag such as "</thi" until the next chunk completes it.
  let pending = "";

  return (chunk: string): string => {
    let buffer = pending + chunk;
    pending = "";
    let output = "";

    while (buffer.length > 0) {
      if (inside) {
        const end = buffer.indexOf(CLOSE);
        if (end === -1) {
          // Keep only enough to recognise a tag straddling the boundary.
          pending = tailThatMightBeATag(buffer, CLOSE);
          return output;
        }
        buffer = buffer.slice(end + CLOSE.length);
        inside = false;
        continue;
      }

      const start = buffer.indexOf(OPEN);
      if (start === -1) {
        const keep = tailThatMightBeATag(buffer, OPEN);
        output += buffer.slice(0, buffer.length - keep.length);
        pending = keep;
        return output;
      }

      output += buffer.slice(0, start);
      buffer = buffer.slice(start + OPEN.length);
      inside = true;
    }

    return output;
  };
}

/** The longest suffix of `text` that could be the start of `tag`. */
function tailThatMightBeATag(text: string, tag: string): string {
  const maxOverlap = Math.min(tag.length - 1, text.length);
  for (let length = maxOverlap; length > 0; length -= 1) {
    if (tag.startsWith(text.slice(text.length - length))) return text.slice(text.length - length);
  }
  return "";
}

/**
 * Convert a provider's SSE body into a stream of plain text.
 *
 * Buffers by line because an SSE event can be split across network chunks --
 * parsing each chunk independently drops tokens at the seams, which shows up as
 * words missing from the middle of an answer.
 *
 * Two failure modes are handled explicitly, both learned the hard way:
 *
 * - **Silence.** A read that never settles would hold the connection open
 *   indefinitely, so each read races an idle timer. Exceeding it closes the
 *   stream and keeps whatever text arrived, rather than discarding a nearly
 *   complete answer.
 * - **Rejection.** Any error inside `pull` must be handled here. An earlier
 *   version let it escape, which surfaced as an unhandledRejection that took down
 *   the route instead of failing one request.
 */
function toTextStream(
  body: ReadableStream<Uint8Array>,
  extractDelta: (payload: unknown) => string,
  options: { idleMs: number; label: string },
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const reader = body.getReader();
  const stripReasoning = createReasoningStripper();
  let buffer = "";
  let closed = false;

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (closed) return;

      try {
        const result = await readWithIdleTimeout(reader, options.idleMs);

        if (result.timedOut) {
          console.error(`[llm:${options.label}] stream idle for ${options.idleMs}ms; closing`);
          closed = true;
          flushLine(buffer, controller);
          controller.close();
          void reader.cancel("idle timeout");
          return;
        }

        if (result.done) {
          closed = true;
          flushLine(buffer, controller);
          controller.close();
          return;
        }

        buffer += decoder.decode(result.value, { stream: true });
        const lines = buffer.split("\n");
        // The final element may be a partial line; keep it for the next pull.
        buffer = lines.pop() ?? "";
        for (const line of lines) flushLine(line, controller);
      } catch (cause) {
        // Close rather than error: the reader keeps the partial answer, which is
        // more useful than an empty failure, and the cause is logged server-side.
        console.error(`[llm:${options.label}] stream failed`, cause);
        closed = true;
        controller.close();
        void reader.cancel("stream error").catch(() => undefined);
      }
    },

    cancel(reason) {
      // Propagate cancellation so a closed browser tab stops the upstream call
      // instead of leaving it generating until it completes.
      closed = true;
      void reader.cancel(reason).catch(() => undefined);
    },
  });

  function flushLine(line: string, controller: ReadableStreamDefaultController<Uint8Array>) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) return;

    const data = trimmed.slice(5).trim();
    if (!data || data === "[DONE]") return;

    try {
      const text = stripReasoning(extractDelta(JSON.parse(data)));
      if (text) controller.enqueue(encoder.encode(text));
    } catch {
      // A malformed chunk is skipped rather than failing the whole answer. The
      // alternative is losing a complete response to one bad frame.
    }
  }
}

/**
 * Read one chunk, giving up if nothing arrives within `idleMs`.
 *
 * Reports a timeout as a value rather than throwing, so the caller can close the
 * stream cleanly and keep the text received so far.
 */
async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  idleMs: number,
): Promise<{ done: boolean; value?: Uint8Array; timedOut: boolean }> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const idle = new Promise<{ done: boolean; timedOut: true }>((resolve) => {
    timer = setTimeout(() => resolve({ done: true, timedOut: true }), idleMs);
  });

  try {
    const winner = await Promise.race([
      reader.read().then((result) => ({ ...result, timedOut: false as const })),
      idle,
    ]);
    return winner as { done: boolean; value?: Uint8Array; timedOut: boolean };
  } finally {
    clearTimeout(timer);
  }
}

