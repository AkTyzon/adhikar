"use client";

import { Languages, Phone, Scale } from "lucide-react";

import { LANGUAGES } from "@/lib/languages";

export function Navbar({
  language,
  onLanguageChange,
}: {
  language: string;
  onLanguageChange: (code: string) => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--line)] bg-navy-900 text-white">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
        <a href="#main" className="flex items-center gap-2.5 font-bold" aria-label="Adhikar, home">
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-lg bg-saffron-600 text-white"
          >
            <Scale className="size-5" strokeWidth={2.25} />
          </span>
          <span className="leading-tight">
            <span className="block text-base tracking-tight">ADHIKAR</span>
            {/* lang is set so a screen reader pronounces the Devanagari correctly
                rather than reading it as mispronounced English. */}
            <span lang="hi" className="block text-xs font-medium text-navy-200">
              अधिकार
            </span>
          </span>
        </a>

        <div className="ms-auto flex flex-wrap items-center gap-2 sm:gap-3">
          <div className="flex items-center gap-2">
            <label htmlFor="language" className="flex items-center gap-1.5 text-xs font-medium text-navy-200">
              <Languages className="size-4" aria-hidden="true" />
              Language
            </label>
            <select
              id="language"
              value={language}
              onChange={(event) => onLanguageChange(event.target.value)}
              className="rounded-lg border border-navy-600 bg-navy-800 px-2.5 py-1.5 text-sm font-medium text-white"
            >
              {LANGUAGES.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.nativeName}
                </option>
              ))}
            </select>
          </div>

          {/* A tel: link rather than plain text: on a phone, which is how most
              users in distress will arrive, this is one tap to call. */}
          <a
            href="tel:15100"
            className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white"
          >
            <Phone className="size-3.5" aria-hidden="true" />
            NALSA 15100
            <span className="visually-hidden">— free legal aid helpline, tap to call</span>
          </a>
        </div>
      </div>
    </header>
  );
}
