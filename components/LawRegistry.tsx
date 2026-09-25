"use client";

import { useMemo, useState } from "react";
import { ExternalLink, Search } from "lucide-react";

import { type Act, indiaCodeUrl, searchRegistry, sectionsOf } from "@/lib/legal-db";
import { Badge, Card } from "@/components/ui/primitives";

/** Browsable registry of the Acts and sections Adhikar can verify against. */
export function LawRegistry() {
  const [query, setQuery] = useState("");
  const results = useMemo(() => searchRegistry(query), [query]);

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-1 text-lg font-bold">The law Adhikar checks against</h2>
        <p className="mb-4 text-sm text-[var(--ink-muted)]">
          Every section cited in an answer is verified against this registry. It is not a complete
          statute book — it is the set of provisions Adhikar can confirm, which is why an answer can
          say &ldquo;unverified&rdquo; about a section that does in fact exist.
        </p>

        <div className="relative">
          <label htmlFor="registry-search" className="visually-hidden">
            Search Acts and sections
          </label>
          <Search
            className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-navy-400"
            aria-hidden="true"
          />
          <input
            id="registry-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search: dowry, deposit, UPI, possession, wages…"
            className="hc-border w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] py-2.5 pe-3 ps-9 text-sm"
          />
        </div>

        {/* Result counts announced politely: a search that silently narrows a list
            tells a non-sighted user nothing. */}
        <p aria-live="polite" className="mt-2 text-xs text-[var(--ink-muted)]">
          {query
            ? `${results.acts.length} Act${results.acts.length === 1 ? "" : "s"} and ${results.sections.length} section${results.sections.length === 1 ? "" : "s"} match.`
            : `${results.acts.length} Acts in the registry.`}
        </p>
      </Card>

      {query && results.sections.length > 0 ? (
        <Card aria-labelledby="matching-sections">
          <h3 id="matching-sections" className="mb-3 text-sm font-bold">
            Matching sections
          </h3>
          <ul className="space-y-2.5">
            {results.sections.slice(0, 25).map((section) => (
              <li
                key={`${section.actId}-${section.number}`}
                className="hc-border rounded-lg border border-[var(--line)] p-3"
              >
                <p className="flex flex-wrap items-center gap-2 font-semibold">
                  <Badge tone="info">{section.actId}</Badge>
                  Section {section.number} — {section.heading}
                </p>
                <p className="mt-1 text-sm text-[var(--ink-muted)]">{section.plain}</p>
                {section.previously ? (
                  <p className="mt-1 text-xs text-[var(--ink-muted)]">Previously {section.previously}</p>
                ) : null}
                {section.consequence ? (
                  <p className="mt-1 text-xs font-medium text-[var(--ink-muted)]">{section.consequence}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <ul className="grid gap-3 sm:grid-cols-2">
        {results.acts.map((act) => (
          <li key={act.id}>
            <ActCard act={act} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ActCard({ act }: { act: Act }) {
  const sections = sectionsOf(act.id);

  return (
    <Card className="h-full">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="info">{act.shortName}</Badge>
        <Badge tone="neutral">{act.year}</Badge>
        <Badge tone="neutral">
          {sections.length} section{sections.length === 1 ? "" : "s"}
        </Badge>
      </div>
      <h3 className="font-bold">{act.title}</h3>
      {act.replaces ? (
        <p className="mt-0.5 text-xs text-[var(--ink-muted)]">Replaced the {act.replaces}</p>
      ) : null}
      <p className="mt-2 text-sm text-[var(--ink-muted)]">{act.summary}</p>

      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-semibold">
          Sections in the registry
        </summary>
        <ul className="mt-2 space-y-1.5">
          {sections.map((section) => (
            <li key={section.number} className="text-sm">
              <span className="font-semibold">s.{section.number}</span>{" "}
              <span className="text-[var(--ink-muted)]">{section.heading}</span>
            </li>
          ))}
        </ul>
      </details>

      <a
        href={indiaCodeUrl(act)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-saffron-ink underline underline-offset-2 dark:text-saffron-400"
      >
        Official text on India Code
        <ExternalLink className="size-3.5" aria-hidden="true" />
        <span className="visually-hidden"> (opens in a new tab)</span>
      </a>
    </Card>
  );
}
