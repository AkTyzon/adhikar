"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, FileText, MessagesSquare } from "lucide-react";

import { ApiKeyPanel } from "@/components/ApiKeyPanel";
import { DisclaimerModal } from "@/components/DisclaimerModal";
import { DocumentUploader } from "@/components/DocumentUploader";
import { EmergencyBar } from "@/components/EmergencyBar";
import { HeroSearch } from "@/components/HeroSearch";
import { LawRegistry } from "@/components/LawRegistry";
import { LegalResponseViewer } from "@/components/LegalResponseViewer";
import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/primitives";
import { DEFAULT_LANGUAGE } from "@/lib/languages";

export interface AdhikarAppProps {
  /** Provider label resolved on the server, or null when no key is configured. */
  providerLabel: string | null;
  /** Question from ?question=, set when a form submitted before hydration. */
  initialQuestion: string;
}

type TabId = "ask" | "document" | "registry";

const TABS: ReadonlyArray<{ id: TabId; label: string; icon: typeof MessagesSquare }> = [
  { id: "ask", label: "Ask & Rights Assist", icon: MessagesSquare },
  { id: "document", label: "Upload Document", icon: FileText },
  { id: "registry", label: "Legal Registry", icon: BookOpen },
];

export function AdhikarApp({ providerLabel, initialQuestion }: AdhikarAppProps) {
  const [tab, setTab] = useState<TabId>("ask");
  const [language, setLanguage] = useState(DEFAULT_LANGUAGE);
  const [question, setQuestion] = useState(initialQuestion);
  const [answer, setAnswer] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [aidOpen, setAidOpen] = useState(false);
  // A key the visitor supplied in this browser, forwarded as a header per request.
  const [byoKey, setByoKey] = useState<string | null>(null);

  // Retained so a second question cancels the first rather than interleaving two
  // streams into the same buffer.
  const abortRef = useRef<AbortController | null>(null);
  const answerRef = useRef<HTMLDivElement>(null);

  const run = useCallback(
    async (endpoint: string, body: unknown) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStreaming(true);
      setAnswer("");
      setNotice(null);
      setError(null);

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            // Sent per request rather than held server-side, so the key never
            // outlives the question it was used for.
            ...(byoKey ? { "x-gemini-api-key": byoKey } : {}),
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        const contentType = response.headers.get("content-type") ?? "";

        // A JSON body means either an error or the offline fallback path; a text
        // body means a live stream.
        if (contentType.includes("application/json")) {
          const payload = (await response.json()) as {
            answer?: string | null;
            notice?: string;
            error?: string;
          };
          if (!response.ok) {
            setError(payload.error ?? "Something went wrong.");
          } else {
            if (payload.answer) setAnswer(payload.answer);
            if (payload.notice) setNotice(payload.notice);
            if (!payload.answer && payload.notice) setError(null);
          }
          return;
        }

        if (!response.ok || !response.body) {
          setError("The service did not respond as expected. Please try again.");
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        // Accumulated locally and flushed into state, so React batches renders
        // instead of re-rendering the markdown tree on every token.
        let buffered = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffered += decoder.decode(value, { stream: true });
          setAnswer(buffered);
        }
      } catch (cause) {
        // An abort is the user asking something else, not a failure.
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError("Could not reach Adhikar. Check your connection and try again.");
      } finally {
        setStreaming(false);
        // Move focus to the answer so a keyboard user is not left at the top of
        // the page hunting for what just changed.
        answerRef.current?.focus();
      }
    },
    [byoKey],
  );

  const ask = useCallback(
    (value: string) => {
      if (value.trim().length < 5) return;
      setTab("ask");
      void run("/api/chat", { question: value.trim(), language });
    },
    [language, run],
  );

  const analyse = useCallback(
    (documentText: string, docQuestion: string) => {
      void run("/api/analyze-doc", { documentText, question: docQuestion, language });
    },
    [language, run],
  );

  // A form submitted before React hydrated performs a native GET to
  // /?question=... . Running it here means that submit is honoured rather than
  // silently reloading the page, which is what it did before.
  const ranInitial = useRef(false);
  useEffect(() => {
    if (ranInitial.current) return;
    ranInitial.current = true;
    if (initialQuestion.trim().length < 5) return;

    // Deferred rather than called inline. Setting state synchronously inside an
    // effect triggers a second render pass before the first has painted, and it
    // reads better too: the question is on screen before "Working…" replaces it.
    const handle = setTimeout(() => ask(initialQuestion), 0);
    return () => clearTimeout(handle);
  }, [initialQuestion, ask]);

  return (
    <>
      <a href="#main" className="skip-link bg-saffron-600 px-4 py-3 font-bold text-white">
        Skip to main content
      </a>

      <Navbar language={language} onLanguageChange={setLanguage} />
      <EmergencyBar />

      <main id="main" className="mx-auto w-full max-w-6xl px-4 py-6 sm:py-8">
        {/* The disclaimer sits above the product, not beneath it. A reader who
            stops after the first screen must still have seen it. */}
        <div className="hc-border mb-6 rounded-lg border border-saffron-500/40 bg-saffron-100/70 p-3 text-sm dark:bg-saffron-600/15">
          <p className="text-saffron-ink dark:text-saffron-100">
            <strong>Adhikar provides AI-generated legal information for educational purposes only.</strong>{" "}
            It is not a substitute for professional legal advice. For formal representation, consult a
            registered Advocate.{" "}
            <button
              type="button"
              onClick={() => setAidOpen(true)}
              className="font-bold underline underline-offset-2"
            >
              You may qualify for a free lawyer
            </button>
            .
          </p>
        </div>

        {providerLabel === null || byoKey ? (
          <div className="mb-6">
            <ApiKeyPanel onChange={setByoKey} />
          </div>
        ) : null}

        <HeroSearch
          question={question}
          onQuestionChange={setQuestion}
          onSubmit={ask}
          busy={streaming}
          providerLabel={byoKey ? "Google Gemini · gemini-flash-latest (your key)" : providerLabel}
        />

        <div className="mt-8">
          {/* Manual-activation tabs: arrow keys move between tabs and Enter or
              Space selects, which is the ARIA pattern for tabs whose panels are
              expensive to render. */}
          <div role="tablist" aria-label="Adhikar tools" className="flex flex-wrap gap-1 border-b border-[var(--line)]">
            {TABS.map(({ id, label, icon: Icon }) => {
              const selected = tab === id;
              return (
                <button
                  key={id}
                  role="tab"
                  id={`tab-${id}`}
                  aria-selected={selected}
                  aria-controls={`panel-${id}`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => setTab(id)}
                  onKeyDown={(event) => {
                    const order = TABS.map((item) => item.id);
                    const index = order.indexOf(tab);
                    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                      event.preventDefault();
                      const next =
                        event.key === "ArrowRight"
                          ? order[(index + 1) % order.length]!
                          : order[(index - 1 + order.length) % order.length]!;
                      setTab(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }
                  }}
                  className={`hc-border inline-flex items-center gap-2 rounded-t-lg border border-b-0 px-4 py-2.5 text-sm font-semibold ${
                    selected
                      ? "border-[var(--line)] bg-[var(--surface)] text-saffron-ink dark:text-saffron-400"
                      : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink)]"
                  }`}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </button>
              );
            })}
          </div>

          <div className="pt-5">
            <section
              role="tabpanel"
              id="panel-ask"
              aria-labelledby="tab-ask"
              hidden={tab !== "ask"}
              tabIndex={-1}
              ref={answerRef}
            >
              <LegalResponseViewer
                answer={answer}
                streaming={streaming}
                language={language}
                notice={notice}
                error={error}
              />
            </section>

            <section role="tabpanel" id="panel-document" aria-labelledby="tab-document" hidden={tab !== "document"}>
              <div className="grid gap-5 lg:grid-cols-2">
                <DocumentUploader onAnalyse={analyse} busy={streaming} />
                <LegalResponseViewer
                  answer={answer}
                  streaming={streaming}
                  language={language}
                  notice={notice}
                  error={error}
                />
              </div>
            </section>

            <section role="tabpanel" id="panel-registry" aria-labelledby="tab-registry" hidden={tab !== "registry"}>
              <LawRegistry />
            </section>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => setAidOpen(true)}>
            Free legal aid & emergency contacts
          </Button>
        </div>
      </main>

      <DisclaimerModal open={aidOpen} onClose={() => setAidOpen(false)} />
    </>
  );
}
