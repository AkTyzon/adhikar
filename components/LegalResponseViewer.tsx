"use client";

import { AlertTriangle, BadgeCheck, CircleHelp, ExternalLink, Loader2 } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { type Citation, auditCitations } from "@/lib/citations";
import { getLanguage } from "@/lib/languages";
import { Badge, Callout, Card } from "@/components/ui/primitives";

/**
 * Renders an answer, plus the result of checking its citations.
 *
 * The citation panel is the part that matters. An answer citing four sections
 * where three verify and one does not is a different thing from an answer where
 * all four verify, and the reader is the person who needs to know which they are
 * looking at. Hiding that distinction would make the verification pointless.
 */
export function LegalResponseViewer({
  answer,
  streaming,
  language,
  notice,
  error,
}: {
  answer: string;
  streaming: boolean;
  language: string;
  notice?: string | null;
  error?: string | null;
}) {
  // Recomputed as the stream grows. Cheap: regex over a few kilobytes.
  const audit = answer ? auditCitations(answer) : undefined;
  const tag = getLanguage(language).tag;

  if (error) {
    return (
      <Callout tone="danger" title="That did not work">
        {error}
      </Callout>
    );
  }

  if (!answer && !streaming) {
    return (
      <Card className="text-sm text-[var(--ink-muted)]">
        <p>
          Ask a question, pick one of the situations above, or upload a document. Every answer names
          the sections it relies on, and each one is checked against Adhikar&rsquo;s registry of
          Indian statutes before you see it.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {notice ? <Callout tone="caution">{notice}</Callout> : null}

      {/* Answers arrive progressively; a live region announces the update without
          moving the reader's focus away from what they were doing. */}
      <Card>
        <div aria-live="polite" aria-busy={streaming}>
          {streaming && !answer ? (
            <p className="flex items-center gap-2 text-sm text-[var(--ink-muted)]">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Working through your question…
            </p>
          ) : null}

          <div
            lang={tag}
            className="prose-adhikar max-w-none text-[0.95rem] leading-relaxed [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-bold [&_h2:first-child]:mt-0 [&_li]:my-1 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:ps-5 [&_p]:my-2 [&_strong]:font-semibold [&_ul]:my-2 [&_ul]:list-disc [&_ul]:ps-5"
          >
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                // react-markdown escapes content by default; these overrides only
                // adjust presentation. No raw HTML plugin is enabled, so markup in
                // a model response is rendered as text rather than as elements.
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="font-medium text-saffron-ink underline underline-offset-2 dark:text-saffron-400"
                  >
                    {children}
                    <span className="visually-hidden"> (opens in a new tab)</span>
                  </a>
                ),
                table: ({ children }) => (
                  <div className="my-3 overflow-x-auto">
                    <table className="w-full border-collapse text-sm">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="border-b-2 border-[var(--line)] p-2 text-start font-semibold">{children}</th>
                ),
                td: ({ children }) => <td className="border-b border-[var(--line)] p-2 align-top">{children}</td>,
              }}
            >
              {answer}
            </Markdown>
          </div>

          {streaming && answer ? (
            <p className="mt-3 flex items-center gap-2 text-xs text-[var(--ink-muted)]">
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
              Still writing…
            </p>
          ) : null}
        </div>
      </Card>

      {/* Citations are checked once the stream finishes: mid-stream a section
          number can be half-written, and flashing "unverified" at a reader who is
          watching text appear would be alarming and wrong. */}
      {!streaming && audit ? <CitationPanel audit={audit} /> : null}
    </div>
  );
}

function CitationPanel({ audit }: { audit: ReturnType<typeof auditCitations> }) {
  if (audit.uncited) {
    return (
      <Callout tone="caution" title="No specific sections were cited">
        This answer does not point to a particular section of any Act, so there is nothing for
        Adhikar to check. Treat it as general orientation and ask a lawyer before acting on it.
      </Callout>
    );
  }

  return (
    <Card aria-labelledby="citations-heading">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 id="citations-heading" className="text-sm font-bold">
          Sections cited
        </h3>
        <Badge tone="verified">
          <BadgeCheck className="size-3.5" aria-hidden="true" />
          {audit.verified} verified
        </Badge>
        {audit.unverified > 0 ? (
          <Badge tone="caution">
            <AlertTriangle className="size-3.5" aria-hidden="true" />
            {audit.unverified} unverified
          </Badge>
        ) : null}
      </div>

      <ul className="space-y-2.5">
        {audit.citations.map((citation) => (
          <CitationRow key={`${citation.actId ?? "?"}-${citation.number}`} citation={citation} />
        ))}
      </ul>

      <p className="mt-4 border-t border-[var(--line)] pt-3 text-xs text-[var(--ink-muted)]">
        Verified means the Act and section exist in Adhikar&rsquo;s registry. The registry is not a
        complete statute book, so unverified does not mean invented — it means Adhikar could not
        confirm it, and you should check it on India Code before relying on it.
      </p>
    </Card>
  );
}

function CitationRow({ citation }: { citation: Citation }) {
  const verified = citation.status === "verified";

  return (
    <li className="hc-border rounded-lg border border-[var(--line)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 font-semibold">
            {verified ? (
              <BadgeCheck className="size-4 shrink-0 text-emerald-600" aria-hidden="true" />
            ) : (
              <CircleHelp className="size-4 shrink-0 text-saffron-600" aria-hidden="true" />
            )}
            <span>
              Section {citation.number}
              {citation.act ? ` — ${citation.act.shortName}` : ""}
            </span>
            {/* The status is text as well as an icon and a colour: severity must
                survive greyscale and colour vision deficiency. */}
            <Badge tone={verified ? "verified" : "caution"}>
              {verified ? "Verified" : citation.status === "unknown-section" ? "Unconfirmed section" : "Unknown law"}
            </Badge>
          </p>

          {citation.section ? (
            <p className="mt-1 text-sm font-medium">{citation.section.heading}</p>
          ) : null}
          {citation.section ? (
            <p className="mt-1 text-sm text-[var(--ink-muted)]">{citation.section.plain}</p>
          ) : null}
          {citation.section?.previously ? (
            <p className="mt-1 text-xs text-[var(--ink-muted)]">
              Previously {citation.section.previously}
            </p>
          ) : null}
          {citation.section?.consequence ? (
            <p className="mt-1 text-xs font-medium text-[var(--ink-muted)]">
              {citation.section.consequence}
            </p>
          ) : null}
          {citation.caution ? (
            <p className="mt-2 text-xs font-medium text-saffron-ink dark:text-saffron-400">
              {citation.caution}
            </p>
          ) : null}
        </div>

        {citation.url ? (
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-saffron-ink underline underline-offset-2 dark:text-saffron-400"
          >
            India Code
            <ExternalLink className="size-3" aria-hidden="true" />
            <span className="visually-hidden">
              — official text of the {citation.act?.title}, opens in a new tab
            </span>
          </a>
        ) : null}
      </div>
    </li>
  );
}
