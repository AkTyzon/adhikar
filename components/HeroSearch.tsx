"use client";

import { Briefcase, CreditCard, Home, Search, Shield, Train } from "lucide-react";
import type { ComponentType } from "react";

import { SCENARIOS, type Scenario } from "@/lib/scenarios";
import { Button } from "@/components/ui/primitives";

const ICONS: Record<Scenario["icon"], ComponentType<{ className?: string }>> = {
  shield: Shield,
  train: Train,
  home: Home,
  "credit-card": CreditCard,
  briefcase: Briefcase,
};

export function HeroSearch({
  question,
  onQuestionChange,
  onSubmit,
  busy,
}: {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (question: string) => void;
  busy: boolean;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-4xl">
          Know your rights. Navigate legal documents.
          <span className="block text-saffron-ink dark:text-saffron-400">Simple and direct.</span>
        </h1>
        <p className="mt-3 max-w-2xl text-[var(--ink-muted)]">
          Ask in your own words, in your own language. Adhikar explains what Indian law says, cites
          the exact section, and checks every citation before showing it to you.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(question);
        }}
        className="flex flex-col gap-2 sm:flex-row"
        role="search"
      >
        <div className="flex-1">
          <label htmlFor="question" className="visually-hidden">
            Describe your legal question or situation
          </label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute start-3 top-1/2 size-5 -translate-y-1/2 text-navy-400"
              aria-hidden="true"
            />
            <input
              id="question"
              name="question"
              type="text"
              value={question}
              maxLength={1000}
              onChange={(event) => onQuestionChange(event.target.value)}
              placeholder="Ask any legal question in plain language…"
              aria-describedby="question-hint"
              className="hc-border w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] py-3 pe-4 ps-10 text-[0.95rem]"
            />
          </div>
          <p id="question-hint" className="mt-1.5 text-xs text-[var(--ink-muted)]">
            For example: my landlord is keeping my deposit. English, हिंदी, Hinglish, தமிழ், తెలుగు,
            मराठी, বাংলা or ಕನ್ನಡ.
          </p>
        </div>
        <Button type="submit" aria-disabled={busy || question.trim().length < 5} className="sm:h-[50px] sm:px-6">
          {busy ? "Working…" : "Ask Adhikar"}
        </Button>
      </form>

      <div>
        <h2 id="scenarios-heading" className="mb-2 text-sm font-bold text-[var(--ink-muted)]">
          Common situations
        </h2>
        {/* A list, so a screen reader announces how many options there are. */}
        <ul aria-labelledby="scenarios-heading" className="flex flex-wrap gap-2">
          {SCENARIOS.map((scenario) => {
            const Icon = ICONS[scenario.icon];
            return (
              <li key={scenario.id}>
                <button
                  type="button"
                  onClick={() => {
                    onQuestionChange(scenario.question);
                    onSubmit(scenario.question);
                  }}
                  aria-disabled={busy}
                  className="hc-border inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3.5 py-2 text-sm font-medium hover:border-saffron-500"
                >
                  <Icon className="size-4 text-saffron-600" aria-hidden="true" />
                  {scenario.label}
                  {/* The chip label is short; the full question is what a
                      non-sighted user needs to know they are about to ask. */}
                  <span className="visually-hidden">— asks: {scenario.question}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
