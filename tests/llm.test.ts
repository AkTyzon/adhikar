/**
 * Provider selection, request construction, and reasoning suppression.
 *
 * No network here: these assert the request we *would* send and the filtering we
 * apply to what comes back. The behaviour they pin was all found empirically
 * against Ollama, and each test records what went wrong before the fix.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildEndpoint, createReasoningStripper, resolveProvider } from "../lib/llm";

const NONE = {} as NodeJS.ProcessEnv;
const env = (extra: Record<string, string>) => extra as unknown as NodeJS.ProcessEnv;

describe("provider selection", () => {
  it("selects nothing when no key or local model is configured", () => {
    assert.equal(resolveProvider(NONE), undefined);
  });

  it("selects a local model from ADHIKAR_LOCAL_MODEL", () => {
    const provider = resolveProvider(env({ ADHIKAR_LOCAL_MODEL: "qwen3:8b" }));
    assert.equal(provider?.id, "local");
    assert.equal(provider?.model, "qwen3:8b");
    assert.equal(provider?.onDevice, true);
  });

  it("defaults to Ollama's endpoint", () => {
    const provider = resolveProvider(env({ ADHIKAR_LOCAL_MODEL: "mistral" }));
    assert.equal(provider?.baseUrl, "http://127.0.0.1:11434/v1");
  });

  it("accepts any OpenAI-compatible server and trims a trailing slash", () => {
    // LM Studio, llama.cpp and vLLM all expose this shape on their own ports.
    const provider = resolveProvider(
      env({ ADHIKAR_LOCAL_MODEL: "x", ADHIKAR_LOCAL_BASE_URL: "http://127.0.0.1:1234/v1/" }),
    );
    assert.equal(provider?.baseUrl, "http://127.0.0.1:1234/v1");
  });

  it("prefers a configured local model over a stray cloud key", () => {
    // Choosing on-device inference is a privacy decision. A key left in the
    // environment by something else must not silently send the document away.
    const provider = resolveProvider(
      env({ ADHIKAR_LOCAL_MODEL: "qwen3:8b", ANTHROPIC_API_KEY: "sk-ant-x", OPENAI_API_KEY: "sk-y" }),
    );
    assert.equal(provider?.id, "local");
  });

  it("gives a local model far longer to respond than a hosted one", () => {
    const local = resolveProvider(env({ ADHIKAR_LOCAL_MODEL: "qwen3:8b" }))!;
    const cloud = resolveProvider(env({ OPENAI_API_KEY: "sk-y" }))!;
    // A single wall-clock deadline used to abort healthy local generations.
    assert.ok((local.setupTimeoutMs ?? 0) > (cloud.setupTimeoutMs ?? 30_000));
    assert.ok((local.idleTimeoutMs ?? 0) > 60_000);
  });

  it("orders cloud providers Gemini, then OpenAI, then Anthropic", () => {
    assert.equal(resolveProvider(env({ GOOGLE_GENERATIVE_AI_API_KEY: "g", OPENAI_API_KEY: "o" }))?.id, "google");
    assert.equal(resolveProvider(env({ OPENAI_API_KEY: "o", ANTHROPIC_API_KEY: "a" }))?.id, "openai");
    assert.equal(resolveProvider(env({ ANTHROPIC_API_KEY: "a" }))?.id, "anthropic");
  });
});

describe("request construction", () => {
  it("suppresses a reasoning model's thinking phase by default", () => {
    // Measured against qwen3:8b through Ollama: with thinking on, a 250-token
    // budget went entirely into the `reasoning` field and produced zero content
    // tokens, so no answer ever arrived.
    const provider = resolveProvider(env({ ADHIKAR_LOCAL_MODEL: "qwen3:8b" }))!;
    const body = buildEndpoint(provider, { system: "s", user: "u" }).body as Record<string, unknown>;
    assert.equal(body.reasoning_effort, "none");
  });

  it("allows thinking back on explicitly", () => {
    const provider = resolveProvider(
      env({ ADHIKAR_LOCAL_MODEL: "qwen3:8b", ADHIKAR_LOCAL_THINKING: "1" }),
    )!;
    const body = buildEndpoint(provider, { system: "s", user: "u" }).body as Record<string, unknown>;
    assert.ok(!("reasoning_effort" in body));
  });

  it("posts to the chat-completions path of the configured base URL", () => {
    const provider = resolveProvider(
      env({ ADHIKAR_LOCAL_MODEL: "m", ADHIKAR_LOCAL_BASE_URL: "http://host:9/v1" }),
    )!;
    assert.equal(buildEndpoint(provider, { system: "s", user: "u" }).url, "http://host:9/v1/chat/completions");
  });

  it("never puts a cloud key in a URL", () => {
    // Query strings are recorded by access logs and proxies; keys belong in headers.
    const configs: Record<string, string>[] = [
      { GOOGLE_GENERATIVE_AI_API_KEY: "secret-g" },
      { OPENAI_API_KEY: "secret-o" },
      { ANTHROPIC_API_KEY: "secret-a" },
    ];
    for (const config of configs) {
      const provider = resolveProvider(env(config))!;
      const endpoint = buildEndpoint(provider, { system: "s", user: "u" });
      assert.ok(!endpoint.url.includes("secret-"), `${provider.id} leaked its key into the URL`);
    }
  });

  it("sends the system prompt separately from the user's question", () => {
    // The document and the user's words are data; the operator's instructions are
    // not. Keeping them in distinct fields is what preserves that boundary.
    const provider = resolveProvider(env({ OPENAI_API_KEY: "k" }))!;
    const body = buildEndpoint(provider, { system: "OPERATOR", user: "USER" }).body as {
      messages: { role: string; content: string }[];
    };
    assert.deepEqual(
      body.messages.map((m) => [m.role, m.content]),
      [["system", "OPERATOR"], ["user", "USER"]],
    );
  });
});

describe("reasoning suppression in the stream", () => {
  it("removes a whole think block", () => {
    const strip = createReasoningStripper();
    assert.equal(strip("A<think>hidden</think>B"), "AB");
  });

  it("removes a block whose tags are split across chunks", () => {
    // The case a per-chunk regex gets wrong: an SSE frame can end mid-tag, and a
    // stateless filter then emits "<thi" to the reader.
    const strip = createReasoningStripper();
    const output = ["Hello <thi", "nk>internal mus", "ings</thi", "nk> answer."].map(strip).join("");
    assert.equal(output, "Hello  answer.");
  });

  it("passes ordinary text through untouched", () => {
    const strip = createReasoningStripper();
    assert.equal(["plain ", "text"].map(strip).join(""), "plain text");
  });

  it("drops everything after an unclosed opening tag", () => {
    // Better to show nothing than to show a reader the model talking to itself.
    const strip = createReasoningStripper();
    assert.equal(strip("keep<think>dropped forever"), "keep");
  });

  it("handles a think block spanning many chunks", () => {
    const strip = createReasoningStripper();
    const chunks = ["visible ", "<think>", "a", "b", "c", "</think>", "more"];
    assert.equal(chunks.map(strip).join(""), "visible more");
  });
});
