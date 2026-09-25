/**
 * Small UI primitives.
 *
 * Hand-written rather than pulled from a component library. Three reasons: the
 * dependency tree stays at zero known vulnerabilities, the accessibility
 * behaviour is visible in this file instead of inherited from a black box, and
 * there is nothing here complex enough to justify the weight.
 */

import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Card({
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"section">) {
  return (
    <section
      className={cn(
        "hc-border rounded-[var(--radius-card)] border bg-[var(--surface)] p-5 sm:p-6",
        "border-[var(--line)] shadow-sm",
        className,
      )}
      {...rest}
    >
      {children}
    </section>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  // Saffron 600 on white gives 4.6:1 for the button label at this weight.
  primary: "bg-saffron-600 text-white hover:bg-saffron-500 focus-visible:bg-saffron-500",
  secondary: "bg-navy-900 text-white hover:bg-navy-800 dark:bg-navy-700 dark:hover:bg-navy-600",
  ghost: "bg-transparent text-[var(--ink)] hover:bg-navy-100 dark:hover:bg-navy-800",
  danger: "bg-danger-600 text-white hover:bg-danger-700",
};

export function Button({
  variant = "primary",
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"button"> & { variant?: ButtonVariant }) {
  return (
    <button
      className={cn(
        "hc-border inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
        "text-sm font-semibold transition-colors",
        // aria-disabled rather than disabled, so the control stays in the
        // accessibility tree and keeps announcing itself while busy.
        "aria-disabled:cursor-progress aria-disabled:opacity-70",
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

type Tone = "neutral" | "verified" | "caution" | "danger" | "info";

const BADGE_TONES: Record<Tone, string> = {
  neutral: "bg-navy-100 text-navy-900 dark:bg-navy-800 dark:text-navy-100",
  verified: "bg-emerald-100 text-emerald-700 dark:bg-emerald-700/25 dark:text-emerald-100",
  caution: "bg-saffron-100 text-saffron-ink dark:bg-saffron-600/25 dark:text-saffron-100",
  danger: "bg-danger-100 text-danger-700 dark:bg-danger-700/25 dark:text-danger-100",
  info: "bg-navy-100 text-navy-700 dark:bg-navy-800 dark:text-navy-100",
};

export function Badge({
  tone = "neutral",
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"span"> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "hc-border inline-flex items-center gap-1.5 rounded-full border border-current/20",
        "px-2.5 py-0.5 text-xs font-semibold",
        BADGE_TONES[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

/**
 * A callout. `role="alert"` is applied only for the danger tone: an alert
 * interrupts a screen reader immediately, which is right for a safety warning and
 * wrong for an informational note.
 */
export function Callout({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const accent: Record<Tone, string> = {
    neutral: "border-l-navy-400",
    verified: "border-l-emerald-600",
    caution: "border-l-saffron-500",
    danger: "border-l-danger-600",
    info: "border-l-navy-600",
  };

  return (
    <div
      role={tone === "danger" ? "alert" : "note"}
      className={cn(
        "hc-border rounded-lg border border-[var(--line)] border-l-4 bg-[var(--surface)] p-4",
        accent[tone],
        className,
      )}
    >
      {title ? <p className="mb-1 font-semibold">{title}</p> : null}
      <div className="text-sm text-[var(--ink-muted)]">{children}</div>
    </div>
  );
}

export function SectionHeading({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="mb-3 text-lg font-bold tracking-tight sm:text-xl">
      {children}
    </h2>
  );
}
