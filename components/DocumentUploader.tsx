"use client";

import { useRef, useState } from "react";
import { FileText, Lock, Upload } from "lucide-react";

import { ExtractionError, type ExtractionResult, extractText } from "@/lib/doc-extract";
import { Badge, Button, Callout, Card } from "@/components/ui/primitives";

/**
 * Document drop zone.
 *
 * A native file input does the work; the drop zone is an enhancement layered on
 * top. That ordering is deliberate — drag and drop is unusable by keyboard and
 * by most assistive technology, so it can never be the only route to a feature.
 */
export function DocumentUploader({
  onAnalyse,
  busy,
}: {
  onAnalyse: (text: string, question: string) => void;
  busy: boolean;
}) {
  const [extracted, setExtracted] = useState<ExtractionResult | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [question, setQuestion] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setExtracted(null);
    // Strip any path component before display: the name is attacker-controlled.
    setFileName(file.name.replace(/^.*[\\/]/, "").slice(0, 120));

    try {
      setExtracted(await extractText(file));
    } catch (cause) {
      setError(
        cause instanceof ExtractionError ? cause.message : "That file could not be read.",
      );
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <h2 id="upload-heading" className="mb-1 text-lg font-bold">
          Upload a document
        </h2>
        <p className="mb-4 flex items-start gap-1.5 text-sm text-[var(--ink-muted)]">
          <Lock className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden="true" />
          <span>
            Your file is read <strong>in your browser</strong>. Only the text needed to answer your
            question is sent, and nothing is saved to any server.
          </span>
        </p>

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void handleFile(event.dataTransfer.files[0]);
          }}
          className={`hc-border rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
            dragging ? "border-saffron-500 bg-saffron-100/60" : "border-[var(--line)]"
          }`}
        >
          <Upload className="mx-auto mb-2 size-7 text-navy-400" aria-hidden="true" />
          <label htmlFor="document" className="block cursor-pointer font-semibold">
            Choose a file
            <span className="font-normal text-[var(--ink-muted)]"> or drag it here</span>
          </label>
          <input
            ref={inputRef}
            id="document"
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => void handleFile(event.target.files?.[0])}
            aria-describedby="document-hint"
            className="mx-auto mt-3 block max-w-full text-sm"
          />
          <p id="document-hint" className="mt-2 text-xs text-[var(--ink-muted)]">
            PDF, Word (.docx) or plain text, up to 12&nbsp;MB. Scanned pages and photographs cannot
            be read — there is no OCR.
          </p>
        </div>

        {error ? (
          <div className="mt-4">
            <Callout tone="danger" title="That file could not be read">
              {error}
            </Callout>
          </div>
        ) : null}

        {extracted ? (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <FileText className="size-4 text-emerald-600" aria-hidden="true" />
              <span className="text-sm font-semibold">{fileName}</span>
              <Badge tone="verified">{extracted.kind.toUpperCase()}</Badge>
              {extracted.pages ? <Badge tone="neutral">{extracted.pages} pages</Badge> : null}
              <Badge tone="neutral">{extracted.text.length.toLocaleString("en-IN")} characters</Badge>
              {extracted.truncated ? <Badge tone="caution">Shortened to fit</Badge> : null}
            </div>

            <div>
              <label htmlFor="doc-question" className="block text-sm font-semibold">
                What do you want to know about it?
              </label>
              <p id="doc-question-hint" className="mb-1.5 text-xs text-[var(--ink-muted)]">
                Leave this blank for a plain-language summary, the red flags, and what to do next.
              </p>
              <input
                id="doc-question"
                type="text"
                value={question}
                maxLength={1000}
                onChange={(event) => setQuestion(event.target.value)}
                aria-describedby="doc-question-hint"
                placeholder="For example: can they increase the rent mid-term?"
                className="hc-border w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2.5 text-sm"
              />
            </div>

            <Button onClick={() => onAnalyse(extracted.text, question)} aria-disabled={busy}>
              {busy ? "Analysing…" : "Analyse this document"}
            </Button>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
